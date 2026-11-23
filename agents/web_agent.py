import logging
from contextlib import aclosing
from typing import Any
from starlette.concurrency import run_in_threadpool

from langchain.agents import create_agent
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig

import config
import prompts
from tools import agentic_tools, tool_utils
from tools.web_session import WebResearchSession
from utils import helpers, llm_client

_logger = logging.getLogger(__name__)


def _completed(
    messages: list[Any], results: list[dict[str, Any]], summary: str
) -> dict[str, Any]:
    """Return the final state of the web research session."""
    return {
        "web_search_history": [*messages, AIMessage(content=summary)],
        "web_results": results,
        "user_feedback": "",
        "feedback_requested": "",
        "next_node": "planning_node",
        "sub_agent_message": summary,
        "next_node_context": "",
        "resume_node": "",
    }


def _needs_feedback(
    messages: list[Any], results: list[dict[str, Any]], question: str
) -> dict[str, Any]:
    """Return the state of the web research session when human feedback is requested."""
    return {
        "web_search_history": [
            *messages,
            AIMessage(content=f"Requesting human feedback: {question}"),
        ],
        "web_results": results,
        "user_feedback": "",
        "feedback_requested": question,
        "next_node": "human_clarification",
        "sub_agent_message": "",
        "next_node_context": "",
        "resume_node": "web_agent_node",
    }


def _completion_summary(terminal: dict[str, Any]) -> str:
    """Generate a summary of the web research session's completion status."""
    parts = [terminal["message"], f"Stop reason: {terminal['stop_reason']}."]
    if terminal["supported_focuses"]:
        parts.append(
            "Supported focuses: " + ", ".join(terminal["supported_focuses"]) + "."
        )
    if terminal["unresolved_gaps"]:
        parts.append("Unresolved gaps: " + ", ".join(terminal["unresolved_gaps"]) + ".")
    return " ".join(parts)


async def run(
    state: dict[str, Any],
    run_config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Runs the ReAct agent to perform web research."""
    query = (state.get("agent_query") or "").strip()
    saved = state.get("web_research_state") or {}
    if saved.get("paused"):
        query = saved.get("query") or query
    session = await run_in_threadpool(
        WebResearchSession.restore, saved, list(state.get("web_results", []) or [])
    )

    def with_checkpoint(update: dict[str, Any], paused: bool = False) -> dict[str, Any]:
        update["web_research_state"] = session.snapshot(query, paused)
        if paused:
            update["next_node_context"] = query
        return update

    if not query:
        return with_checkpoint(
            _completed(
                [],
                list(state.get("web_results", []) or []),
                "Web research skipped: no query.",
            )
        )

    llm = llm_client.get_llm()
    if llm is None:
        raise RuntimeError("LLM is not available. Cannot run web research.")

    history = list(state.get("web_search_history", []) or [])
    messages = [
        *history,
        SystemMessage(content=await run_in_threadpool(session.available_results)),
        HumanMessage(content=query),
    ]
    user_profile = state.get("user_profile") or {}
    if user_profile:
        messages.insert(
            -1,
            SystemMessage(
                content=f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
            ),
        )

    agent_config = run_config.copy() if run_config else RunnableConfig()
    agent_config.setdefault("metadata", {})
    agent_config["metadata"].update(
        {"is_background_task": True, "agent_name": "web_agent"}
    )
    maximum_tool_calls = (
        config.WEB_MAX_SEARCHES
        + config.WEB_MAX_EXTRACTIONS
        + config.WEB_MAX_PASSAGE_READS
        + 4
    )
    agent_config["recursion_limit"] = maximum_tool_calls * 2 + 1

    agent = create_agent(
        model=llm,
        tools=[*session.tools(), agentic_tools.ask_human_feedback],
        system_prompt=prompts.web_prompt,
    )
    await adispatch_custom_event(
        "reasoning_header", "Searching the web...", config=run_config
    )

    new_messages = []
    try:
        # Failure recovery: preserve messages from completed steps even if a later model/tool step fails.
        async with aclosing(
            agent.astream(
                {"messages": messages}, config=agent_config, stream_mode="values"
            )
        ) as stream:
            async for response in stream:
                new_messages = response.get("messages", [])[len(messages) :]
                if session.terminal and any(
                    isinstance(message, ToolMessage)
                    and message.name == "finish_research"
                    for message in new_messages
                ):
                    break

        feedback = tool_utils.extract_last_tool_call_args(
            {"messages": new_messages}, agentic_tools.ask_human_feedback.name
        ).get("request_feedback", "")
        if feedback:
            return with_checkpoint(
                _needs_feedback(
                    new_messages,
                    list(state.get("web_results", []) or []),
                    str(feedback).strip(),
                ),
                paused=True,
            )

        if session.terminal:
            return with_checkpoint(
                _completed(
                    new_messages,
                    session.terminal["selected"],
                    _completion_summary(session.terminal),
                )
            )

        return with_checkpoint(
            _completed(
                new_messages,
                list(state.get("web_results", []) or []),
                "Web research ended without a validated selection. Working evidence is retained for further research; answer evidence is unchanged.",
            )
        )
    except Exception:
        _logger.exception("Web research failed")
        answered_calls = {
            message.tool_call_id
            for message in new_messages
            if isinstance(message, ToolMessage)
        }
        pending_calls = [
            call
            for message in new_messages
            if isinstance(message, AIMessage)
            for call in message.tool_calls
            if call["id"] not in answered_calls
        ]
        for call in pending_calls:
            new_messages.append(
                ToolMessage(
                    tool_call_id=call["id"],
                    name=call["name"],
                    content="Research was interrupted before this tool response was received. Do not assume it succeeded; inspect the retained session state.",
                )
            )
        if session.terminal:
            return with_checkpoint(
                _completed(
                    new_messages,
                    session.terminal["selected"],
                    _completion_summary(session.terminal),
                )
            )
        summary = "Web research failed. Previously selected answer evidence and working research evidence were retained."

    return with_checkpoint(
        _completed(new_messages, list(state.get("web_results", []) or []), summary)
    )
