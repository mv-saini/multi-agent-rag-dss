from typing import List, Optional
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
from utils import helpers, llm_client
from tools import db_tools, tool_utils, agentic_tools
from models.agents import SpatialAgentOutput, SpatialContext
import prompts
import json


def get_spatial_context_prompt(spatial_context: List[dict]) -> str:
    return f"""
### Current Spatial Context
{helpers.json_to_markdown(spatial_context) if spatial_context else "None"}    
"""


async def run(state: dict, run_config: RunnableConfig = None) -> dict:
    """
    Executes the ReAct agent to autonomously use tools to find relevant spatial data.
    """

    spatial_search_history = state.get("spatial_search_history", [])
    agent_query = state.get("agent_query", "")
    spatial_context = state.get("spatial_context", {})
    user_profile = state.get("user_profile", {})

    llm = llm_client.get_llm()
    if llm is None:
        raise ValueError("LLM is not available. Cannot find relevant spatial data.")

    @tool(args_schema=SpatialAgentOutput, return_direct=True)
    async def submit_spatial_data(
        spatial_context: Optional[List[SpatialContext]] = list, message: str = ""
    ):
        """Call this tool EXACTLY ONCE to submit the final list of relevant spatial context."""
        return {"spatial_context": spatial_context, "message": message}

    tools = [
        db_tools.get_regions,
        db_tools.get_provinces,
        db_tools.get_cities,
        db_tools.get_hazard_ids,
        db_tools.get_hazard_data_file_paths,
        db_tools.get_region_by_name,
        db_tools.get_province_by_name,
        db_tools.get_city_by_name,
        submit_spatial_data,
        agentic_tools.ask_human_feedback,
    ]

    messages_payload = []
    new_messages = []

    # Add user profile to the payload
    if user_profile:
        user_profile_prompt = (
            f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
        )
        user_profile_message = SystemMessage(content=user_profile_prompt)
        messages_payload.append(user_profile_message)

    messages_payload.append(
        SystemMessage(content=get_spatial_context_prompt(spatial_context))
    )

    if spatial_search_history:
        messages_payload.extend(spatial_search_history)

    chat_prompt = ""

    if agent_query:
        chat_prompt = f"""{agent_query}"""
        chat_message = HumanMessage(content=chat_prompt)
        new_messages.append(chat_message)
        messages_payload.append(chat_message)

    agent = create_agent(model=llm, tools=tools, system_prompt=prompts.spatial_prompt)

    spatial_config = run_config.copy() if run_config else RunnableConfig()
    spatial_config.setdefault("metadata", {})
    spatial_config["metadata"]["is_background_task"] = True

    await adispatch_custom_event(
        "reasoning_header", "Creating spatial context...", config=run_config
    )

    try:
        response = await agent.ainvoke(
            {"messages": messages_payload}, config=spatial_config
        )

        ask_human_feedback_tool = tool_utils.extract_last_tool_call_args(
            response=response, tool_name="ask_human_feedback"
        )

        if ask_human_feedback_tool and ask_human_feedback_tool.get("request_feedback"):
            feedback = ask_human_feedback_tool["request_feedback"]
            new_messages.append(
                AIMessage(content=f"Requesting human feedback: {feedback}")
            )
            return {
                "feedback_requested": feedback,
                "spatial_context": spatial_context,
                "spatial_search_history": new_messages,
                "user_feedback": "",
                "next_node": "human_clarification",
                "resume_node": "spatial_agent_node",
                "next_node_context": "",
                "sub_agent_message": "",
            }

        submit_spatial = tool_utils.extract_last_tool_call_args(
            response=response, tool_name="submit_spatial_data"
        )

        if not submit_spatial:
            raise ValueError(
                "The spatial agent did not call the submit_spatial_data tool. "
            )

        spatial_agent_message = submit_spatial.get(
            "message", "Spatial data selection completed."
        )
        new_messages.append(AIMessage(content=spatial_agent_message))

        spatial_context_objects: List[SpatialContext] = submit_spatial.get(
            "spatial_context", []
        )

        if isinstance(spatial_context, str):
            spatial_context = json.loads(spatial_context)

        spatial_context = [
            obj.model_dump() if hasattr(obj, "model_dump") else obj
            for obj in spatial_context_objects
        ]

        return {
            "spatial_search_history": new_messages,
            "spatial_context": spatial_context,
            "user_feedback": "",
            "feedback_requested": "",
            "next_node": "planning_node",
            "resume_node": "",
            "sub_agent_message": spatial_agent_message,
            "next_node_context": "",
        }

    except Exception as e:
        fallback_message = "Nothing found."
        new_messages.append(AIMessage(content=fallback_message))

        return {
            "spatial_search_history": new_messages,
            "spatial_context": spatial_context,
            "user_feedback": "",
            "feedback_requested": "",
            "next_node": "planning_node",
            "resume_node": "",
            "sub_agent_message": fallback_message,
            "next_node_context": "",
        }
