from __future__ import annotations

import json
import os
from typing import Any

from langchain_core.tools import tool
from tavily import AsyncTavilyClient

import config
from models.agents import WebResearchItem


def _get_tavily_client() -> AsyncTavilyClient:
    api_key = os.getenv("TAVILY_API_KEY")

    if not api_key:
        raise RuntimeError("TAVILY_API_KEY is not configured.")

    return AsyncTavilyClient(api_key=api_key)


@tool
async def search_web(
    query: str, max_results: int = config.MAX_SEARCH_RESULTS
) -> dict[str, Any]:
    """Search the web for evidence useful to report generation."""
    client = _get_tavily_client()
    response = await client.search(
        query=query,
        search_depth="advanced",
        max_results=max(1, max_results),
        include_answer=False,
        include_raw_content=False,
        include_images=False,
    )

    return {
        "query": query,
        "results": [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score"),
                "query": query,
                "extracted": False,
            }
            for item in response.get("results", []) or []
        ],
    }


@tool
async def extract_webpages(
    urls: list[str],
    max_urls: int = config.MAX_EXTRACT_URLS,
    max_content_chars: int = config.MAX_CONTENT_CHARS,
) -> dict[str, Any]:
    """Extract additional content from a small number of promising webpages."""
    clean_urls: list[str] = []

    for url in urls:
        if not isinstance(url, str):
            continue

        url = url.strip()
        if url and url not in clean_urls:
            clean_urls.append(url)

        if len(clean_urls) >= max(0, max_urls):
            break

    if not clean_urls:
        return {"results": [], "message": "No valid URLs."}

    client = _get_tavily_client()
    response = await client.extract(
        urls=clean_urls,
        extract_depth="basic",
        format="markdown",
        include_images=False,
    )

    return {
        "results": [
            {
                "title": "",
                "url": item.get("url", ""),
                "content": (item.get("raw_content", "") or "")[:max_content_chars],
                "score": None,
                "query": "",
                "extracted": True,
            }
            for item in response.get("results", []) or []
        ],
        "failed_results": response.get("failed_results", []) or [],
    }


def normalize_result(
    item: WebResearchItem | dict[str, Any],
) -> dict[str, Any] | None:
    if hasattr(item, "model_dump"):
        item = item.model_dump()

    if not isinstance(item, dict):
        return None

    url = str(item.get("url") or "").strip()
    content = str(item.get("content") or "").strip()
    if not url or not content:
        return None

    score = item.get("score")
    return {
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "content": content,
        "score": score if isinstance(score, (int, float)) else None,
        "query": str(item.get("query") or "").strip(),
        "extracted": bool(item.get("extracted", False)),
    }


def serialize_results(
    results: list[WebResearchItem | dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered_urls: list[str] = []
    by_url: dict[str, dict[str, Any]] = {}

    for item in results:
        normalized = normalize_result(item)
        if normalized is None:
            continue

        url = normalized["url"]
        existing = by_url.get(url)
        if existing is None:
            by_url[url] = normalized
            ordered_urls.append(url)
            continue

        if normalized["extracted"] or len(normalized["content"]) > len(
            existing["content"]
        ):
            merged = {**existing, **normalized}
            if not merged["title"]:
                merged["title"] = existing["title"]
            if not merged["query"]:
                merged["query"] = existing["query"]
            by_url[url] = merged

    return [by_url[url] for url in ordered_urls]


def merge_results(
    stored_results: list[dict[str, Any]],
    new_results: list[WebResearchItem | dict[str, Any]],
) -> list[dict[str, Any]]:
    return serialize_results(stored_results + new_results)


def select_results(
    stored_results: list[dict[str, Any]],
    indices: list[Any],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()

    for index in indices:
        if isinstance(index, bool) or not isinstance(index, int) or index in seen:
            continue
        if 0 <= index < len(stored_results):
            selected.append(stored_results[index])
            seen.add(index)

    return selected


def format_available_results(
    results: list[dict[str, Any]],
    *,
    max_visible: int = config.MAX_RESULTS_VISIBLE_TO_AGENT,
) -> str:
    if not results:
        return "### AVAILABLE WEB RESULTS\nNo results have been collected yet."

    visible_results = results[:max_visible]
    entries = []
    for index, result in enumerate(visible_results):
        content = " ".join(str(result.get("content", "")).split())
        score = result.get("score")
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        extracted = "yes" if result.get("extracted") else "no"
        entries.append(
            f"[{index}]\n"
            f"Title: {result.get('title', '')}\n"
            f"URL: {result.get('url', '')}\n"
            f"Score: {score_text}\n"
            f"Extracted: {extracted}\n"
            f"Summary: {content[:config.RESULT_PREVIEW_CHARS]}"
        )

    hidden_count = len(results) - len(visible_results)
    hidden_note = (
        f"\n\n{hidden_count} additional results are stored but not shown. "
        "Select only from the visible indices."
        if hidden_count > 0
        else ""
    )
    return (
        "### AVAILABLE WEB RESULTS\n\n"
        + "\n\n".join(entries)
        + hidden_note
        + "\n\nWhen finishing, return only the useful result indices."
    )


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
