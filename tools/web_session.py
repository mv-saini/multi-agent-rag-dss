import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any
from starlette.concurrency import run_in_threadpool

from langchain_core.tools import BaseTool, tool

import config
from models.agents import (
    ExtractWebpagesInput,
    FinishResearchInput,
    SearchWebInput,
    WebEvidenceSelection,
)
from tools import web_results, web_tools

_logger = logging.getLogger(__name__)
_MAX_URLS_PER_EXTRACTION = 3
_MAX_NO_PROGRESS_SEARCHES = 2


def _merge_session_results(stored: list[dict[str, Any]], new_results: list[Any]):
    previous = {item["result_id"]: item for item in stored}
    merged = web_results.merge_results(stored, new_results)
    added = [
        item
        for item in merged
        if (
            item["result_id"] not in previous
            or {p["passage_id"] for p in item["passages"]}
            != {p["passage_id"] for p in previous[item["result_id"]]["passages"]}
            or set(item["focuses"]) != set(previous[item["result_id"]]["focuses"])
        )
    ]
    return merged, added


@dataclass
class WebResearchSession:
    results: list[dict[str, Any]]
    search_calls: int = 0
    extraction_calls: int = 0
    passage_reads: int = 0
    no_progress_searches: int = 0
    searched_queries: set[str] = field(default_factory=set)
    extracted_urls: set[tuple[str, str]] = field(default_factory=set)
    terminal: dict[str, Any] = field(default_factory=dict)
    _merge_lock: asyncio.Lock = field(
        default_factory=asyncio.Lock, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.results = web_results.serialize_results(self.results)

    def snapshot(self, query: str, paused: bool = False) -> dict[str, Any]:
        """Checkpoint working evidence."""
        return {
            "query": query,
            "paused": paused,
            "results": self.results,
            "search_calls": self.search_calls,
            "extraction_calls": self.extraction_calls,
            "passage_reads": self.passage_reads,
            "no_progress_searches": self.no_progress_searches,
            "searched_queries": sorted(self.searched_queries),
            "extracted_urls": [list(item) for item in sorted(self.extracted_urls)],
        }

    @classmethod
    def restore(
        cls, snapshot: dict[str, Any], selected: list[dict[str, Any]]
    ) -> "WebResearchSession":
        session = cls(web_results.merge_results(snapshot.get("results", []), selected))
        if snapshot.get("paused"):
            for field_name in (
                "search_calls",
                "extraction_calls",
                "passage_reads",
                "no_progress_searches",
            ):
                setattr(session, field_name, snapshot.get(field_name, 0))
            session.searched_queries = set(snapshot.get("searched_queries", []))
            session.extracted_urls = {
                tuple(item) for item in snapshot.get("extracted_urls", [])
            }
        return session

    async def add_results(self, new_results: list[Any]) -> list[dict[str, Any]]:
        """Retain candidates in memory and report new passages or focus coverage."""
        async with self._merge_lock:
            merged, added = await run_in_threadpool(
                _merge_session_results, self.results, new_results
            )
            self.results = merged
            return added

    def available_results(self) -> str:
        """Return a formatted string of available results."""
        return web_results.format_available_results(self.results) + (
            f"\nSearches remaining: {max(0, config.WEB_MAX_SEARCHES - self.search_calls)}; "
            f"extractions remaining: {max(0, config.WEB_MAX_EXTRACTIONS - self.extraction_calls)}; "
            f"inspections remaining: {max(0, config.WEB_MAX_PASSAGE_READS - self.passage_reads)}."
        )

    def tools(self) -> list[BaseTool]:
        """Return the tools for searching and extracting web results and finishing web research."""
        session = self

        @tool("search_web", args_schema=SearchWebInput)
        async def search(
            query: str,
            focus: str = "general",
            mode: str = "general",
        ) -> dict[str, Any]:
            """Search one research focus using a general, deep, or recent strategy."""
            normalized_query = " ".join(query.split())
            if not normalized_query:
                return {"results": [], "message": "The query was empty."}
            query_key = f"{mode}:{normalized_query}"
            if query_key in session.searched_queries:
                return {"results": [], "message": "That query was already used."}
            if session.search_calls >= config.WEB_MAX_SEARCHES:
                return {
                    "results": [],
                    "message": "Search budget exhausted. Inspect or extract existing evidence, then finish.",
                }
            session.searched_queries.add(query_key)
            session.search_calls += 1
            try:
                raw_result = await asyncio.wait_for(
                    web_tools.search_web.ainvoke(
                        {
                            "query": query,
                            "focus": focus,
                            "mode": mode,
                            "max_results": config.WEB_MAX_RESULTS_PER_SEARCH,
                        }
                    ),
                    timeout=config.WEB_TOOL_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                session.searched_queries.discard(query_key)
                _logger.warning(
                    "Web search failed for %r: %s", query, exc, exc_info=True
                )
                return {
                    "results": [],
                    "message": "The search provider failed. Try another query or finish.",
                }

            result = await run_in_threadpool(web_tools.tool_result_dict, raw_result)
            added = await session.add_results(result.get("results", []))
            session.no_progress_searches = (
                session.no_progress_searches + 1 if not added else 0
            )
            result["results"] = await run_in_threadpool(
                web_results.format_available_results, added
            )
            if session.no_progress_searches >= _MAX_NO_PROGRESS_SEARCHES:
                result["message"] = (
                    "No new passages or focus coverage in two searches. Change strategy: use deep mode, a primary-source query, or another research focus; otherwise finish."
                )
            result["budget"] = {
                "searches_remaining": config.WEB_MAX_SEARCHES - session.search_calls,
                "extractions_remaining": config.WEB_MAX_EXTRACTIONS
                - session.extraction_calls,
            }
            return result

        @tool("extract_webpages", args_schema=ExtractWebpagesInput)
        async def extract(urls: list[str], question: str) -> dict[str, Any]:
            """Extract relevant passages from up to three promising webpages."""
            if session.extraction_calls >= config.WEB_MAX_EXTRACTIONS:
                return {"results": [], "message": "Extraction budget exhausted."}
            clean_urls = []
            seen_urls = set()
            for url in urls:
                canonical = web_results.normalize_url(url)
                if (
                    canonical
                    and (canonical, question) not in session.extracted_urls
                    and canonical not in seen_urls
                ):
                    clean_urls.append(url)
                    seen_urls.add(canonical)
                if len(clean_urls) >= _MAX_URLS_PER_EXTRACTION:
                    break
            if not clean_urls:
                return {"results": [], "message": "No new valid URLs to extract."}

            session.extraction_calls += 1
            try:
                raw_result = await asyncio.wait_for(
                    web_tools.extract_webpages.ainvoke(
                        {
                            "urls": clean_urls,
                            "question": question,
                            "max_urls": _MAX_URLS_PER_EXTRACTION,
                        }
                    ),
                    timeout=config.WEB_TOOL_TIMEOUT_SECONDS,
                )
            except Exception as exc:
                _logger.warning("Web extraction failed: %s", exc, exc_info=True)
                return {
                    "results": [],
                    "message": "Webpage extraction failed. Use snippets or other sources.",
                }

            result = await run_in_threadpool(web_tools.tool_result_dict, raw_result)
            known_sources = {item["normalized_url"]: item for item in session.results}
            for item in result.get("results", []):
                source = known_sources.get(item.get("normalized_url"), {})
                item["focuses"] = source.get("focuses", [])
                for passage in item.get("passages", []):
                    passage["focuses"] = list(
                        dict.fromkeys(passage.get("focuses", []) + item["focuses"])
                    )
            added = await session.add_results(result.get("results", []))
            session.extracted_urls.update(
                (web_results.normalize_url(item.get("url", "")), question)
                for item in result.get("results", [])
                if isinstance(item, dict)
            )
            result["results"] = await run_in_threadpool(
                web_results.format_available_results, added
            )
            return result

        @tool
        async def list_sources(offset: int = 0) -> dict[str, Any]:
            """Browse all stored candidate sources, five at a time."""
            if session.passage_reads >= config.WEB_MAX_PASSAGE_READS:
                return {"message": "Evidence inspection budget exhausted."}
            sources = await run_in_threadpool(web_results.rank_results, session.results)
            if session.passage_reads >= config.WEB_MAX_PASSAGE_READS:
                return {"message": "Evidence inspection budget exhausted."}
            if offset < 0 or offset >= len(sources):
                return {"message": "No sources at that offset."}
            session.passage_reads += 1
            return {
                "sources": await run_in_threadpool(
                    web_results.format_available_results, sources[offset : offset + 5]
                ),
                "next_offset": offset + 5 if offset + 5 < len(sources) else None,
                "reads_remaining": config.WEB_MAX_PASSAGE_READS - session.passage_reads,
            }

        @tool
        async def list_passages(result_id: str, offset: int = 0) -> dict[str, Any]:
            """List five passage previews from a source; follow next_offset for more."""
            if session.passage_reads >= config.WEB_MAX_PASSAGE_READS:
                return {"message": "Passage inspection budget exhausted."}
            source = next(
                (item for item in session.results if item["result_id"] == result_id),
                None,
            )
            if source is None or offset < 0 or offset >= len(source["passages"]):
                return {"message": "Unknown source or invalid passage offset."}
            session.passage_reads += 1
            page = source["passages"][offset : offset + 5]
            return {
                "result_id": result_id,
                "passages": [
                    {**p, "text": p["text"][: config.WEB_PASSAGE_PREVIEW_CHARS]}
                    for p in page
                ],
                "next_offset": (
                    offset + 5 if offset + 5 < len(source["passages"]) else None
                ),
                "reads_remaining": config.WEB_MAX_PASSAGE_READS - session.passage_reads,
            }

        @tool
        async def inspect_passage(result_id: str, passage_id: str) -> dict[str, Any]:
            """Read the complete stored passage identified by source and passage ID."""
            if session.passage_reads >= config.WEB_MAX_PASSAGE_READS:
                return {
                    "message": "Passage inspection budget exhausted. Finish with supported evidence."
                }
            for item in session.results:
                if item["result_id"] != result_id:
                    continue
                for passage in item["passages"]:
                    if passage["passage_id"] != passage_id:
                        continue
                    session.passage_reads += 1
                    return {
                        **passage,
                        "result_id": result_id,
                        "reads_remaining": config.WEB_MAX_PASSAGE_READS
                        - session.passage_reads,
                    }
            return {"message": "Unknown source or passage ID."}

        @tool(args_schema=FinishResearchInput)
        async def finish_research(
            evidence: list[WebEvidenceSelection] | None = None,
            supported_focuses: list[str] | None = None,
            unresolved_gaps: list[str] | None = None,
            stop_reason: str = "sufficient_evidence",
            message: str = "Web research completed.",
        ) -> dict[str, Any]:
            """Select useful evidence and finish with a coverage summary."""
            selections = [
                (
                    item
                    if isinstance(item, WebEvidenceSelection)
                    else WebEvidenceSelection(**item)
                )
                for item in (evidence or [])
            ]
            if len({s.result_id for s in selections}) != len(selections):
                return {
                    "message": "Use one evidence entry per source, combining its selected passage IDs."
                }
            by_id = {item["result_id"]: item for item in session.results}
            selected = []
            covered = set()
            for selection in selections:
                source = by_id.get(selection.result_id)
                if source is None:
                    return {"message": f"Unknown result ID: {selection.result_id}"}
                passages = {p["passage_id"]: p for p in source["passages"]}
                if any(key not in passages for key in selection.passage_ids):
                    return {"message": "Unknown passage ID in selection."}
                chosen = [passages[key] for key in dict.fromkeys(selection.passage_ids)]
                selected.append(
                    {
                        **source,
                        "passages": chosen,
                        "content": "\n\n".join(p["text"] for p in chosen),
                        "extracted": any(p["kind"] == "extraction" for p in chosen),
                        "focuses": selection.supported_focuses,
                        "focus": "",
                        "selection_reason": selection.rationale,
                        "limitations": selection.limitations,
                    }
                )
                covered.update(selection.supported_focuses)
            if set(supported_focuses or []) - covered:
                return {
                    "message": "Each supported focus must be linked to selected evidence."
                }
            if not selected and stop_reason == "sufficient_evidence":
                return {
                    "message": "No evidence selected. Use insufficient_evidence or select supporting passages."
                }
            session.terminal = {
                "selected": selected,
                "supported_focuses": sorted(covered),
                "unresolved_gaps": list(unresolved_gaps or []),
                "stop_reason": stop_reason,
                "message": message.strip() or "Web research completed.",
            }
            return {"status": "Research finished."}

        return [
            search,
            extract,
            list_sources,
            list_passages,
            inspect_passage,
            finish_research,
        ]
