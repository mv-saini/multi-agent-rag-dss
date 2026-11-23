from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from typing import Any

from utils import helpers

CITATION_START = "\ue200"
CITATION_DELIMITER = "\ue202"
CITATION_STOP = "\ue201"

_CITATION_RE = re.compile(
    re.escape(CITATION_START)
    + r"cite"
    + re.escape(CITATION_DELIMITER)
    + r"(?P<body>.*?)"
    + re.escape(CITATION_STOP),
    re.DOTALL,
)
_ANY_MARKER_RE = re.compile(
    re.escape(CITATION_START) + r".*?" + re.escape(CITATION_STOP), re.DOTALL
)
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class CitableContext:
    prompt: str
    sources: dict[str, dict[str, Any]]


@dataclass
class ParsedCitations:
    text: str
    sources: dict[str, dict[str, Any]]


def _stable_id(prefix: str, *parts: Any) -> str:
    """Generate a stable ID for a citation source based on its prefix and content."""
    raw = "\x1f".join(str(part or "") for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"


def build_citable_context(retrieved_context: dict[str, Any]) -> CitableContext:
    """Build citable blocks for the retrieved context."""
    sources: dict[str, dict[str, Any]] = {}
    prompt_blocks: list[str] = []

    def add_source(
        *,
        kind: str,
        label: str,
        title: str,
        text: str,
        seed: str,
        page: Any = None,
        url: str | None = None,
    ) -> None:
        block = text
        source_id = _stable_id(kind, seed, block)
        source = {
            "id": source_id,
            "kind": kind,
            "label": label,
            "title": title or "Untitled source",
            "text": block,
            "page": page,
            "url": url,
        }
        sources[source_id] = source
        metadata = [
            f'kind="{html.escape(kind)}"',
            f'label="{html.escape(label)}"',
            f'title="{html.escape(source["title"])}"',
        ]
        if page is not None:
            metadata.append(f'page="{html.escape(str(page))}"')
        if url:
            metadata.append(f'url="{html.escape(url)}"')
        prompt_blocks.append(
            f'<BLOCK id="{source_id}" {" ".join(metadata)}>\n{block}\n</BLOCK>'
        )

    # Add document evidence
    for index, chunk in enumerate(retrieved_context.get("vector_docs", []) or []):
        if isinstance(chunk, dict):
            metadata = chunk.get("metadata", {}) or {}
            content = str(chunk.get("page_content") or "")
        else:
            metadata = getattr(chunk, "metadata", {}) or {}
            content = str(getattr(chunk, "page_content", "") or "")
        if not content.strip():
            continue
        title = str(metadata.get("source") or "Document evidence")
        page = metadata.get("page")
        seed = str(
            metadata.get("id") or metadata.get("parent_id") or f"{title}:{page}:{index}"
        )
        add_source(
            kind="document",
            label=f"D{index + 1}",
            title=title,
            text=content,
            seed=seed,
            page=page,
        )

    # Add web evidence
    for index, result in enumerate(retrieved_context.get("web_results", []) or []):
        content = str(result.get("content") or "")
        if not content.strip():
            continue
        url = str(result.get("url") or "") or None
        title = str(result.get("title") or url or "Web evidence")
        evidence_notes = []
        if result.get("published_date"):
            evidence_notes.append(f"Publication date: {result['published_date']}")
        if result.get("selection_reason"):
            evidence_notes.append(f"Selection rationale: {result['selection_reason']}")
        if result.get("limitations"):
            evidence_notes.append(f"Evidence limitations: {result['limitations']}")
        if result.get("passages"):
            evidence_notes.append("Passage types: " + ", ".join(sorted({p.get("kind", "snippet") for p in result["passages"]})))
        if evidence_notes:
            content = "\n".join(evidence_notes) + "\n\n" + content
        seed = str(result.get("result_id") or url or index)
        add_source(
            kind="web",
            label=f"W{index + 1}",
            title=title,
            text=content,
            seed=seed,
            url=url,
        )

    # Add spatial analysis evidence
    for index, analysis in enumerate(
        retrieved_context.get("spatial_analysis", []) or []
    ):
        text = helpers.format_spatial_analysis([analysis], start_index=index + 1)
        if not text.strip():
            continue
        location = analysis.get("location", {}) if isinstance(analysis, dict) else {}
        location_name = location.get("name", "Unknown location")
        add_source(
            kind="spatial",
            label=f"S{index + 1}",
            title=f"Spatial analysis: {location_name}",
            text=text,
            seed=f"{location_name}:{index}",
        )

    prompt = "### RETRIEVED EVIDENCE\n" + (
        "\n\n".join(prompt_blocks) if prompt_blocks else "No evidence was retrieved."
    )
    return CitableContext(prompt=prompt, sources=sources)


def parse_citations(
    text: str, source_registry: dict[str, dict[str, Any]]
) -> ParsedCitations:
    """Validate model citation markers and replace them with safe UI tokens."""
    used_sources: dict[str, dict[str, Any]] = {}

    def replace(match: re.Match[str]) -> str:
        source_ids = [
            part.strip()
            for part in match.group("body").split(CITATION_DELIMITER)
            if part.strip()
        ]
        valid_ids = [
            source_id
            for source_id in source_ids
            if _SOURCE_ID_RE.fullmatch(source_id) and source_id in source_registry
        ]
        tokens = []
        for source_id in valid_ids:
            if source_id not in used_sources:
                used_sources[source_id] = dict(source_registry[source_id])
            tokens.append(f"[[CITE:{source_id}]]")
        return " ".join(tokens)

    parsed = _CITATION_RE.sub(replace, text)
    parsed = _ANY_MARKER_RE.sub("", parsed)
    partial_start = parsed.rfind(CITATION_START)
    if partial_start >= 0:
        parsed = parsed[:partial_start]
    return ParsedCitations(text=parsed.strip(), sources=used_sources)
