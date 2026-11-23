from langchain_core.messages import AIMessage, SystemMessage, HumanMessage
from utils import llm_client, helpers
from models.agents import AVAILABLE_ROUTES, SupervisorRouter
import prompts
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain.agents import create_agent
from tools import tool_utils, agentic_tools


def _get_available_routes():
    available_choices = {name: desc for name, desc in AVAILABLE_ROUTES.items()}
    return "\n".join([f"- '{name}'" for name, _ in available_choices.items()])


def _get_nodes_visited(nodes_visited: list):
    return "\n".join([f"- {node}" for node in nodes_visited])


def get_plan_prompt(plan: dict, nodes_visited: list, web_results: list):
    route_descriptions = _get_available_routes()
    nodes_descriptions = _get_nodes_visited(nodes_visited)
    tools_selected_prompt = helpers.json_to_markdown(plan.get("selected_tools", []))
    vector_tasks_prompt = helpers.json_to_markdown(plan.get("vector_tasks", {}))
    spatial_context_prompt = helpers.json_to_markdown(plan.get("spatial_context", []))

    return f"""
### AVAILABLE NODES TO ROUTE TO
{route_descriptions}

### CURRENT STATE
* **NODES VISITED SO FAR:** {nodes_descriptions if nodes_descriptions else "None"}
* **CURRENT PLAN:**
- Tools: {tools_selected_prompt if tools_selected_prompt else "None"}
- Vector Tasks: {vector_tasks_prompt if vector_tasks_prompt else "None"}
- Spatial Context: {spatial_context_prompt if spatial_context_prompt else "None"}
- Web Results: {len(web_results)} result(s) retrieved from web search.
"""


async def run(state: dict, run_config: RunnableConfig = None):
    """
    Multi-Agent Supervisor mapping the request to the next agent node.
    """
    supervisor_history: list = state.get("supervisor_history", [])
    plan: dict = state.get("plan", {})
    nodes_visited: list = state.get("nodes_visited", [])
    sub_agent_message: str = state.get("sub_agent_message", "")
    user_profile: dict = state.get("user_profile", {})
    web_results: list = state.get("web_results", [])

    llm = llm_client.get_llm()
    if not llm:
        raise ValueError("System error: No LLM configured for planning.")

    @tool(args_schema=SupervisorRouter, return_direct=True)
    async def submit_decision(next_node: str, next_node_context: str):
        """Call this tool EXACTLY ONCE to submit your decision."""
        return {
            "next_node": next_node,
            "next_node_context": next_node_context,
        }

    plan_message = SystemMessage(
        content=get_plan_prompt(plan, nodes_visited, web_results)
    )

    messages_payload = []
    new_messages = []

    # Add existing messages to the payload
    if supervisor_history:
        messages_payload.extend(supervisor_history)

    chat_prompt = ""
    sub_agent_role = ""

    if sub_agent_message:
        sub_agent_role = nodes_visited[-1] if nodes_visited else "unknown"

        chat_prompt = (
            f"### INFORMATION FROM SUB-AGENT: {sub_agent_role}\n"
            f"{sub_agent_message}\n\n"
            "Based on this new information, route to the appropriate node."
        )

        chat_message = HumanMessage(content=chat_prompt)
        new_messages.append(chat_message)
        messages_payload.append(chat_message)

    # Add user profile to the payload
    if user_profile:
        user_profile_prompt = (
            f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
        )
        user_profile_message = SystemMessage(content=user_profile_prompt)
        messages_payload.append(user_profile_message)

    # Add the plan to the payload
    messages_payload.append(plan_message)

    planning_config = run_config.copy() if run_config else RunnableConfig()
    planning_config.setdefault("metadata", {})
    planning_config["metadata"]["is_background_task"] = True

    agent = create_agent(
        model=llm,
        tools=[submit_decision, agentic_tools.ask_human_feedback],
        system_prompt=prompts.planner_prompt,
    )

    try:
        response = await agent.ainvoke(
            {"messages": messages_payload}, config=planning_config
        )

        ask_human_feedback_tool = tool_utils.extract_last_tool_call_args(
            response=response, tool_name="ask_human_feedback"
        )

        if ask_human_feedback_tool.get("request_feedback"):
            feedback = ask_human_feedback_tool["request_feedback"]
            ai_msg = AIMessage(content=f"Requesting human feedback: {feedback}")
            new_messages.append(ai_msg)
            return {
                "next_node": "human_clarification",
                "feedback_requested": feedback,
                "next_node_context": "",
                "supervisor_history": new_messages,
                "resume_node": "planning_node",
                "user_feedback": "",
                "nodes_visited": {"planning_node": ["human_clarification"]},
            }

        submit_decision_tool = tool_utils.extract_last_tool_call_args(
            response=response, tool_name="submit_decision"
        )

        if not submit_decision_tool or not submit_decision_tool.get("next_node"):
            raise ValueError(
                "The supervisor agent did not call the submit_decision tool. "
            )

        if submit_decision_tool.get("next_node"):
            ai_msg = AIMessage(
                content=f"ROUTING TO: {submit_decision_tool['next_node']} WITH NEXT NODE CONTEXT: {submit_decision_tool['next_node_context']} "
            )
            new_messages.append(ai_msg)

            return {
                "next_node": submit_decision_tool["next_node"],
                "next_node_context": submit_decision_tool["next_node_context"],
                "feedback_requested": "",
                "supervisor_history": new_messages,
                "resume_node": "",
                "user_feedback": "",
                "nodes_visited": {"planning_node": [submit_decision_tool["next_node"]]},
            }
    except Exception as e:
        return {
            "next_node": "planning_node",
            "next_node_context": "Error in routing decision. Check the previous messages for details.",
            "feedback_requested": "",
            "supervisor_history": new_messages,
            "resume_node": "",
            "user_feedback": "",
            "nodes_visited": {"planning_node": ["planning_node"]},
        }
