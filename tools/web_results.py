from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from models.agents import WebResearchItem
import config


def split_passages(content: str) -> list[str]:
    """Split passages at word boundaries"""
    passages = []
    current = ""
    for word in re.findall(r"\S+\s*", content):
        if current and len(current) + len(word) > config.WEB_PASSAGE_CHARS:
            passages.append(current.strip())
            current = ""
        current += word
    if current.strip():
        passages.append(current.strip())
    return passages


def merge_passages(passages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate passages by kind and normalized text, merging queries and focuses."""
    merged = {}
    for passage in passages:
        text = str(passage.get("text") or "").strip()
        if not text:
            continue
        kind = passage.get("kind", "snippet")
        key = hashlib.sha256(
            (kind + "\n" + " ".join(text.split())).encode()
        ).hexdigest()[:12]
        previous = merged.get(key, {})
        merged[key] = {
            "passage_id": key,
            "text": text,
            "kind": kind,
            "queries": list(
                dict.fromkeys(previous.get("queries", []) + passage.get("queries", []))
            ),
            "focuses": list(
                dict.fromkeys(previous.get("focuses", []) + passage.get("focuses", []))
            ),
        }
    return list(merged.values())


_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
}


def normalize_url(url: str) -> str:
    """Normalize a URL by removing tracking parameters and standardizing the scheme and host."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except (AttributeError, ValueError):
        return ""

    if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
        return ""

    host = parts.hostname.casefold()
    if (
        port
        and not (parts.scheme == "http" and port == 80)
        and not (parts.scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in _TRACKING_QUERY_KEYS
        )
    )
    return urlunsplit(("https", host, parts.path.rstrip("/") or "/", query, ""))


def normalize_result(
    item: WebResearchItem | dict[str, Any],
) -> dict[str, Any] | None:
    """Normalize a web research result item, ensuring it has a valid URL and content, and a unique result ID."""
    if hasattr(item, "model_dump"):
        item = item.model_dump()
    if not isinstance(item, dict):
        return None

    url = str(item.get("url") or "").strip()
    content = str(item.get("content") or "").strip()
    normalized_url = normalize_url(url)
    if not normalized_url or not content:
        return None

    query = str(item.get("query") or "").strip()
    focus = str(item.get("focus") or "").strip()
    score = item.get("score")
    passages = merge_passages(
        item.get("passages")
        or [
            {
                "text": passage_text,
                "kind": "extraction" if item.get("extracted") else "snippet",
                "queries": item.get("queries") or ([query] if query else []),
                "focuses": item.get("focuses") or ([focus] if focus else []),
            }
            for passage_text in split_passages(content)
        ]
    )
    return {
        "result_id": hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:12],
        "title": str(item.get("title") or "").strip(),
        "url": url,
        "normalized_url": normalized_url,
        "domain": urlsplit(normalized_url).hostname or "",
        "content": "\n\n".join(p["text"] for p in passages),
        "passages": passages,
        "selection_reason": item.get("selection_reason", ""),
        "limitations": item.get("limitations", ""),
        "score": score if isinstance(score, (int, float)) else None,
        "query": query,
        "queries": (
            list(dict.fromkeys([*(item.get("queries") or []), query]))
            if query
            else list(dict.fromkeys(item.get("queries") or []))
        ),
        "focus": focus,
        "focuses": (
            list(dict.fromkeys([*(item.get("focuses") or []), focus]))
            if focus
            else list(dict.fromkeys(item.get("focuses") or []))
        ),
        "published_date": item.get("published_date"),
        "extracted": bool(item.get("extracted", False)),
    }


def serialize_results(
    results: list[WebResearchItem | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Serialize a list of web research results by normalizing, deduplicating, and merging them by URL."""
    by_url: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for item in results:
        normalized = normalize_result(item)
        if normalized is None:
            continue

        key = normalized["normalized_url"]
        existing = by_url.get(key)
        if existing is None:
            by_url[key] = normalized
            order.append(key)
            continue

        merged = {**existing}
        merged["passages"] = merge_passages(
            existing["passages"] + normalized["passages"]
        )
        merged["content"] = "\n\n".join(p["text"] for p in merged["passages"])
        merged["title"] = normalized["title"] or existing["title"]
        merged["score"] = max(
            (
                value
                for value in (existing.get("score"), normalized.get("score"))
                if isinstance(value, (int, float))
            ),
            default=None,
        )
        merged["queries"] = list(
            dict.fromkeys(existing["queries"] + normalized["queries"])
        )
        merged["focuses"] = list(
            dict.fromkeys(existing["focuses"] + normalized["focuses"])
        )
        merged["published_date"] = normalized.get("published_date") or existing.get(
            "published_date"
        )
        merged["extracted"] = existing["extracted"] or normalized["extracted"]
        for field_name in ("selection_reason", "limitations"):
            merged[field_name] = "\n".join(
                dict.fromkeys(
                    value
                    for value in (existing.get(field_name), normalized.get(field_name))
                    if value
                )
            )
        by_url[key] = merged

    return [by_url[key] for key in order]


def merge_results(
    stored_results: list[dict[str, Any]],
    new_results: list[WebResearchItem | dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge new web research results with stored results"""
    return serialize_results([*stored_results, *new_results])


def rank_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order discovery previews by provider relevance."""
    return sorted(
        serialize_results(results),
        key=lambda item: (item["score"] if item["score"] is not None else -1.0,),
        reverse=True,
    )


def diversify_results(
    results: list[dict[str, Any]], max_per_domain: int | None = None
) -> list[dict[str, Any]]:
    """Order candidates, with an optional domain cap."""
    domain_counts: dict[str, int] = {}
    selected: list[dict[str, Any]] = []
    for item in rank_results(results):
        domain = item["domain"] or item["result_id"]
        if (
            max_per_domain is not None
            and domain_counts.get(domain, 0) >= max_per_domain
        ):
            continue
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        selected.append(item)
    return selected


def select_results(
    stored_results: list[dict[str, Any]], result_ids: list[str]
) -> list[dict[str, Any]]:
    """Select results by their IDs"""
    by_id = {item["result_id"]: item for item in serialize_results(stored_results)}
    return [by_id[key] for key in dict.fromkeys(result_ids) if key in by_id]


def format_available_results(results: list[dict[str, Any]], limit: int = 20) -> str:
    """Format available web results."""

    visible = diversify_results(results)[:limit]
    if not visible:
        return "### AVAILABLE WEB RESULTS\nNo results have been collected yet."

    entries = []
    for result in visible:
        score = result.get("score")
        score_text = f"{score:.3f}" if isinstance(score, (int, float)) else "n/a"
        preview = "\n".join(
            f"Passage {p['passage_id']} ({p['kind']}, {len(p['text'])} chars): "
            + " ".join(p["text"].split())[: config.WEB_PASSAGE_PREVIEW_CHARS]
            for p in result["passages"][:3]
        )
        entries.append(
            f"ID: {result['result_id']}\n"
            f"Title: {result['title']}\n"
            f"URL: {result['url']}\n"
            f"Score: {score_text}\n"
            f"Focuses: {', '.join(result['focuses']) or 'general'}\n"
            f"Extracted: {'yes' if result['extracted'] else 'no'}\n"
            f"Published: {result.get('published_date') or 'unknown'}\n"
            f"Passages: {len(result['passages'])}; first three previews below. Use list_passages for more.\n"
            f"Summary: {preview}"
        )

    return (
        f"### AVAILABLE WEB RESULTS\nShowing {len(visible)} of {len(results)} sources. Use list_sources to browse the session.\n\n"
        + "\n\n".join(entries)
        + "\n\nFinish by selecting useful result IDs and passage IDs with evidence assessments."
    )
