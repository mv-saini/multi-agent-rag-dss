from __future__ import annotations

import json
import os
from typing import Any
from starlette.concurrency import run_in_threadpool

from langchain_core.tools import tool
from tavily import AsyncTavilyClient

import config
from tools import web_results

SEARCH_MODES: dict[str, dict[str, Any]] = {
    "general": {"topic": "general", "search_depth": "basic"},
    "deep": {"topic": "general", "search_depth": "advanced"},
    "recent": {
        "topic": "news",
        "search_depth": "advanced",
        "time_range": "month",
    },
}


def _get_tavily_client() -> AsyncTavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured.")
    return AsyncTavilyClient(api_key=api_key)


@tool
async def search_web(
    query: str,
    focus: str = "general",
    mode: str = "general",
    max_results: int = config.WEB_MAX_RESULTS_PER_SEARCH,
) -> dict[str, Any]:
    """Search for one research focus using a general, deep, or recent strategy."""
    response = await _get_tavily_client().search(
        query=query,
        max_results=max(1, max_results),
        chunks_per_source=3,
        include_published_date=True,
        include_answer=False,
        include_raw_content=False,
        include_images=False,
        **SEARCH_MODES.get(mode, SEARCH_MODES["general"]),
    )

    return await run_in_threadpool(_prepare_search_results, response, query, focus)


def _prepare_search_results(response: dict, query: str, focus: str) -> dict[str, Any]:
    results = []
    for item in response.get("results", []) or []:
        normalized = web_results.normalize_result(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score"),
                "query": query,
                "focus": focus,
                "published_date": item.get("published_date"),
                "extracted": False,
            }
        )
        if normalized:
            results.append(normalized)

    return {
        "results": results,
        "request_id": response.get("request_id"),
        "response_time": response.get("response_time"),
    }


@tool
async def extract_webpages(
    urls: list[str],
    question: str,
    max_urls: int = 3,
) -> dict[str, Any]:
    """Extract passages that are relevant to a focused research question."""
    clean_urls = list(
        dict.fromkeys(
            url.strip()
            for url in urls
            if isinstance(url, str) and web_results.normalize_url(url)
        )
    )[:max_urls]
    if not clean_urls:
        return {"results": [], "message": "No valid URLs were supplied."}

    response = await _get_tavily_client().extract(
        urls=clean_urls,
        query=question,
        chunks_per_source=3,
        extract_depth="basic",
        format="markdown",
        include_images=False,
    )

    return await run_in_threadpool(_prepare_extraction_results, response, question)


def _prepare_extraction_results(response: dict, question: str) -> dict[str, Any]:
    results = []
    for item in response.get("results", []) or []:
        normalized = web_results.normalize_result(
            {
                "url": item.get("url", ""),
                "content": item.get("raw_content", "") or "",
                "query": question,
                "extracted": True,
            }
        )
        if normalized:
            results.append(normalized)

    return {
        "results": results,
        "failed_results": response.get("failed_results", []) or [],
        "request_id": response.get("request_id"),
        "response_time": response.get("response_time"),
    }


def tool_result_dict(result: Any) -> dict[str, Any]:
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return {"content": result}
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    return {"result": result}
