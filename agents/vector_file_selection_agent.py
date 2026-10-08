from typing import List, Optional
from langchain_core.callbacks import adispatch_custom_event
from models.agents import VectorAgentOutput
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain.agents import create_agent
from langchain_core.tools import tool
from langchain_core.runnables import RunnableConfig
import prompts
from utils import helpers, llm_client
from tools import db_tools, tool_utils, agentic_tools
from models.agents import SearchTask


def get_vector_context_prompt(vector_tasks: List[dict]) -> str:
    return f"""
### CURRENT VECTOR TASKS
{helpers.json_to_markdown(vector_tasks) if vector_tasks else 'None'}
"""


async def run(state: dict, run_config: RunnableConfig = None) -> dict:
    """
    Executes the ReAct agent to autonomously use tools to find relevant files.
    """

    if db_tools.get_files_count() == 0:
        return {
            "feedback_requested": "",
            "vector_tasks": [],
            "vector_search_history": [],
            "user_feedback": "",
            "next_node": "planning_node",
            "resume_node": "",
            "sub_agent_message": "No files available in the system.",
            "next_node_context": "",
        }

    vector_search_history = state.get("vector_search_history", [])
    agent_query = state.get("agent_query", "")
    vector_tasks = state.get("vector_tasks", {})
    user_profile = state.get("user_profile", {})

    llm = llm_client.get_llm()
    if llm is None:
        return {}

    @tool(args_schema=VectorAgentOutput, return_direct=True)
    def submit_selected_files(
        vector_tasks: Optional[List[SearchTask]] = list, message: str = ""
    ):
        """Call this tool EXACTLY ONCE to submit the final list of relevant filenames and queries or empty list."""
        return {"vector_tasks": vector_tasks, "message": message}

    tools = [
        db_tools.get_filenames_paginated,
        db_tools.get_file_details,
        submit_selected_files,
        agentic_tools.ask_human_feedback,
    ]

    messages_payload = []
    new_messages = []

    if user_profile:
        user_profile_prompt = (
            f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
        )
        user_profile_message = SystemMessage(content=user_profile_prompt)
        messages_payload.append(user_profile_message)

    messages_payload.append(
        SystemMessage(content=get_vector_context_prompt(vector_tasks))
    )

    if vector_search_history:
        messages_payload.extend(vector_search_history)

    chat_prompt = ""

    if agent_query:
        chat_prompt = f"""### Target Query\n{agent_query}\n"""
        chat_message = HumanMessage(content=chat_prompt)
        new_messages.append(chat_message)
        messages_payload.append(chat_message)

    agent = create_agent(model=llm, tools=tools, system_prompt=prompts.vector_prompt)

    vector_config = run_config.copy() if run_config else RunnableConfig()
    vector_config.setdefault("metadata", {})
    vector_config["metadata"]["is_background_task"] = True

    await adispatch_custom_event(
        "reasoning_header", "Searching for relevant files...", config=run_config
    )

    try:
        response = await agent.ainvoke(
            {"messages": messages_payload}, config=vector_config
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
                "vector_tasks": vector_tasks,
                "vector_search_history": new_messages,
                "user_feedback": "",
                "next_node": "human_clarification",
                "resume_node": "vector_agent_node",
                "next_node_context": "",
                "sub_agent_message": "",
            }

        submit_vector = tool_utils.extract_last_tool_call_args(
            response=response, tool_name="submit_selected_files"
        )

        if not submit_vector:
            raise ValueError(
                "The vector agent did not call the submit_selected_files tool. "
            )

        vector_agent_message = submit_vector.get(
            "message", "Vector tasks selection completed."
        )

        new_messages.append(AIMessage(content=vector_agent_message))

        vector_tasks_objects: list[SearchTask] = submit_vector.get(
            "vector_tasks", vector_tasks
        )

        if vector_tasks_objects is None:
            vector_tasks_objects = []

        vector_tasks_out = [
            obj.model_dump() if hasattr(obj, "model_dump") else obj
            for obj in vector_tasks_objects
        ]

        return {
            "feedback_requested": "",
            "vector_tasks": vector_tasks_out,
            "vector_search_history": new_messages,
            "user_feedback": "",
            "next_node": "planning_node",
            "resume_node": "",
            "sub_agent_message": vector_agent_message,
            "next_node_context": "",
        }

    except Exception as e:
        fallback_message = "Nothing found."
        new_messages.append(AIMessage(content=fallback_message))

        return {
            "feedback_requested": "",
            "vector_tasks": vector_tasks,
            "vector_search_history": new_messages,
            "user_feedback": "",
            "next_node": "planning_node",
            "resume_node": "",
            "sub_agent_message": fallback_message,
            "next_node_context": "",
        }
