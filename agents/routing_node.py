from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from utils import llm_client
from models.agents import ExecutiveRouter
import prompts


async def run(state: dict, run_config: RunnableConfig = None):
    """Run the router"""

    messages = state.get("messages", [])
    plan = state.get("plan", {})
    user_feedback = state.get("user_feedback", "")

    llm = llm_client.get_llm()
    if not llm:
        raise ValueError("System error: No LLM configured for routing.")

    structured_llm = llm.with_structured_output(ExecutiveRouter)

    plan_exists = bool(plan.get("selected_tools"))

    state_summary = f"""
### CURRENT SYSTEM STATE
* Latest User Feedback: {user_feedback if user_feedback else "None"}
* Plan Status: {"Plan is populated and ready for execution" if plan_exists else "No plan"}
"""

    messages_payload = [
        SystemMessage(content=prompts.router_prompt),
        # *messages,
    ]

    messages_payload.append(SystemMessage(content=state_summary))

    messages_payload.extend(messages)

    if user_feedback:
        messages_payload.append(HumanMessage(content=user_feedback))

    router_config = run_config.copy() if run_config else RunnableConfig()
    router_config.setdefault("metadata", {})
    router_config["metadata"]["is_background_task"] = True

    response: ExecutiveRouter = await structured_llm.ainvoke(
        messages_payload, config=router_config
    )

    return {
        "next_node": response.next_node,
        "user_feedback": "",
    }
