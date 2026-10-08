from typing import Any
from langchain_core.callbacks import adispatch_custom_event
from langchain_core.messages import (
    AIMessage,
    SystemMessage,
    HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langchain.agents import create_agent
import config
import prompts
from models.agents import FinishResearchInput
from tools import agentic_tools
from tools import tool_utils
from tools import web_tools
from utils import helpers, llm_client


def _success_state(
    *,
    new_messages: list[Any],
    web_results: list[dict[str, Any]],
    message: str,
) -> dict[str, Any]:

    completion_message = AIMessage(
        content=message,
    )

    return {
        "web_search_history": [
            *new_messages,
            completion_message,
        ],
        "web_results": web_results,
        "user_feedback": "",
        "feedback_requested": "",
        "next_node": "planning_node",
        "sub_agent_message": message,
        "next_node_context": "",
        "resume_node": "",
    }


def _feedback_state(
    *,
    new_messages: list[Any],
    web_results: list[dict[str, Any]],
    feedback_question: str,
) -> dict[str, Any]:

    feedback_message = AIMessage(
        content=("Requesting human feedback: " f"{feedback_question}")
    )

    return {
        "feedback_requested": feedback_question,
        "web_results": web_results,
        "web_search_history": [
            *new_messages,
            feedback_message,
        ],
        "user_feedback": "",
        "next_node": "human_clarification",
        "resume_node": "web_agent_node",
        "next_node_context": "",
        "sub_agent_message": "",
    }


def _web_limits(
    state: dict[str, Any], run_config: RunnableConfig | None
) -> dict[str, int]:
    defaults = {
        "max_steps": config.MAX_AGENT_STEPS,
        "max_search_calls": config.MAX_SEARCH_CALLS,
        "max_extract_calls": config.MAX_EXTRACT_CALLS,
        "max_search_results": config.MAX_SEARCH_RESULTS,
        "max_extract_urls": config.MAX_EXTRACT_URLS,
        "max_content_chars": config.MAX_CONTENT_CHARS,
        "max_visible_results": config.MAX_RESULTS_VISIBLE_TO_AGENT,
    }
    metadata = (run_config or {}).get("metadata", {})
    overrides = state.get("web_limits") or metadata.get("web_limits") or {}

    for name, value in overrides.items():
        if name in defaults and isinstance(value, int) and not isinstance(value, bool):
            defaults[name] = max(0, value)

    return defaults


async def run(
    state: dict[str, Any],
    run_config: RunnableConfig | None = None,
) -> dict[str, Any]:
    """Run the autonomous web researcher with Python-owned budgets and state."""
    history = list(state.get("web_search_history", []) or [])
    agent_query = (state.get("agent_query") or "").strip()
    user_profile = state.get("user_profile", {})
    stored_results = web_tools.serialize_results(
        list(state.get("web_results", []) or [])
    )
    limits = _web_limits(state, run_config)
    counters = {"steps": 0, "search_calls": 0, "extract_calls": 0}
    searched_queries: set[str] = set()
    terminal: dict[str, Any] = {}

    llm = llm_client.get_llm()
    if llm is None:
        raise RuntimeError("LLM is not available. Cannot run web research.")

    if not agent_query:
        return _success_state(
            new_messages=[],
            web_results=stored_results,
            message="Web research skipped because no research query was provided.",
        )

    @tool("search_web")
    async def bounded_search(query: str, max_results: int = 0) -> dict[str, Any]:
        """Search for evidence, subject to the research budget."""
        nonlocal stored_results
        normalized_query = " ".join(query.split()).casefold()
        if not normalized_query:
            return {"results": [], "message": "The search query was empty."}
        if normalized_query in searched_queries:
            return {"results": [], "message": "An equivalent query was already used."}
        if counters["search_calls"] >= limits["max_search_calls"]:
            return {
                "results": [],
                "message": "Search budget exhausted. Finish with available evidence.",
            }

        searched_queries.add(normalized_query)
        counters["search_calls"] += 1
        requested = max_results or limits["max_search_results"]
        result = web_tools.tool_result_dict(
            await web_tools.search_web.ainvoke(
                {
                    "query": query,
                    "max_results": min(max(1, requested), limits["max_search_results"]),
                }
            )
        )
        stored_results = web_tools.merge_results(
            stored_results, result.get("results", [])
        )
        result["available_results"] = web_tools.format_available_results(
            stored_results[: limits["max_visible_results"]]
        )
        return result

    @tool("extract_webpages")
    async def bounded_extract(urls: list[str]) -> dict[str, Any]:
        """Extract promising sources, subject to the research budget."""
        nonlocal stored_results
        if counters["extract_calls"] >= limits["max_extract_calls"]:
            return {
                "results": [],
                "message": "Extraction budget exhausted. Finish with available evidence.",
            }

        counters["extract_calls"] += 1
        clean_urls = [
            url.strip() for url in urls if isinstance(url, str) and url.strip()
        ]
        result = web_tools.tool_result_dict(
            await web_tools.extract_webpages.ainvoke(
                {
                    "urls": clean_urls[: limits["max_extract_urls"]],
                    "max_urls": limits["max_extract_urls"],
                    "max_content_chars": limits["max_content_chars"],
                }
            )
        )
        for item in result.get("results", []):
            if isinstance(item, dict):
                item["content"] = str(item.get("content") or "")[
                    : limits["max_content_chars"]
                ]
        stored_results = web_tools.merge_results(
            stored_results, result.get("results", [])
        )
        result["available_results"] = web_tools.format_available_results(
            stored_results[: limits["max_visible_results"]]
        )
        return result

    @tool(args_schema=FinishResearchInput, return_direct=True)
    async def finish_research(
        selected_indices: list[int], message: str = "Web research completed."
    ) -> dict[str, Any]:
        """Select useful stored result indices and finish research."""
        terminal["type"] = "finish"
        terminal["selected_results"] = web_tools.select_results(
            stored_results, selected_indices
        )
        terminal["message"] = message.strip() or "Web research completed."
        return {"status": "Research finished successfully."}

    messages = [
        *history,
        SystemMessage(
            content=web_tools.format_available_results(
                stored_results[: limits["max_visible_results"]]
            )
        ),
        HumanMessage(content=agent_query),
    ]
    if user_profile:
        messages.insert(
            -1,
            SystemMessage(
                content=f"### USER PROFILE\n{helpers.json_to_markdown(user_profile)}"
            ),
        )

    tools = [
        bounded_search,
        bounded_extract,
        agentic_tools.ask_human_feedback,
        finish_research,
    ]
    agent = create_agent(model=llm, tools=tools, system_prompt=prompts.web_prompt)
    agent_config = run_config.copy() if run_config else RunnableConfig()
    agent_config.setdefault("metadata", {})
    agent_config["metadata"].update(
        {"is_background_task": True, "agent_name": "web_agent"}
    )
    agent_config["recursion_limit"] = max(2, limits["max_steps"] * 2 + 1)

    await adispatch_custom_event(
        "reasoning_header", "Searching the web...", config=run_config
    )

    try:
        response = await agent.ainvoke({"messages": messages}, config=agent_config)
        response_messages = response.get("messages", [])
        new_messages = [
            message
            for message in response_messages
            if not isinstance(message, SystemMessage)
        ]

        feedback = tool_utils.extract_last_tool_call_args(
            response, agentic_tools.ask_human_feedback.name
        ).get("request_feedback", "")
        if feedback:
            return _feedback_state(
                new_messages=new_messages,
                web_results=stored_results,
                feedback_question=str(feedback).strip(),
            )

        if terminal.get("type") == "finish":
            selected = terminal["selected_results"] or stored_results
            return _success_state(
                new_messages=new_messages,
                web_results=selected,
                message=terminal["message"],
            )

        message = (
            "Web research completed with the evidence collected so far."
            if stored_results
            else "Web research completed, but no usable evidence was found."
        )
        return _success_state(
            new_messages=new_messages, web_results=stored_results, message=message
        )
    except Exception:
        message = (
            "Web research encountered an error and returned the evidence collected before the failure."
            if stored_results
            else "Web research failed before usable evidence could be collected."
        )
        return _success_state(
            new_messages=[], web_results=stored_results, message=message
        )
