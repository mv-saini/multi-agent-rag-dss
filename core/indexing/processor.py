from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter

from langchain_classic.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
import config
from utils import logger
from utils.concurrency import run_ingestion_local
from core.indexing import enhancer
from core.indexing.image_assets import (
    image_data_url,
    image_refs_in_text,
    is_meaningful_image,
)

_logger = logging.getLogger(__name__)

child_text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=config.CHILD_CHUNK_SIZE,
    chunk_overlap=config.CHILD_CHUNK_OVERLAP,
)
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")

_ABSTRACT_TITLES = {
    "abstract",
    "executive summary",
    "summary",
    "sommario",
    "riassunto",
}
_DISCOVERY_SUMMARY_MAX_CHARS = 16_000


def _flatten_pages(pages: list[dict]) -> list[dict]:
    """Convert page Markdown into lines annotated with their source page."""
    lines = []
    for page in pages:
        page_number = page.get("page_number", 1)
        for line in page.get("markdown", "").splitlines():
            lines.append({"line": line, "page": page_number})
    return lines


def create_chunks_by_title(pages: list[dict]):
    """Group Markdown by heading titles to create parent chunks"""
    try:
        if not pages:
            return []

        max_chars = int(getattr(config, "MAX_CHARACTERS", 4500))
        if max_chars < 1:
            raise ValueError("config.MAX_CHARACTERS must be greater than zero")

        sections = []
        current_title = "Document"
        current_lines = []
        current_pages = []
        current_level = 0

        def flush():
            nonlocal current_lines, current_pages
            text = "\n".join(current_lines).strip()
            if text:
                sections.append(
                    {
                        "title": current_title,
                        "text": text,
                        "pages": sorted(set(current_pages), key=lambda p: str(p)),
                        "heading_level": current_level,
                        "image_refs": image_refs_in_text(text),
                    }
                )
            current_lines = []
            current_pages = []

        for item in _flatten_pages(pages):
            line = item["line"]
            match = _HEADING_RE.match(line.strip())
            if match:
                flush()
                current_title = match.group(2).strip()
                current_level = len(match.group(1))
                current_lines = [line]
                current_pages = [item["page"]]
            else:
                current_lines.append(line)
                current_pages.append(item["page"])
        flush()

        # Split long title sections without losing their heading/title relationship.
        parent_chunks = []
        for section in sections:
            text = section["text"]
            if len(text) <= max_chars:
                parent_chunks.append(section)
                continue

            splitter = RecursiveCharacterTextSplitter(
                chunk_size=max_chars,
                chunk_overlap=0,
                separators=["\n\n", "\n", ". ", " ", ""],
            )
            pieces = splitter.split_text(text)
            for part_index, piece in enumerate(pieces, start=1):
                title = section["title"]
                parent_chunks.append(
                    {
                        **section,
                        "title": title,
                        "text": piece,
                        "image_refs": image_refs_in_text(piece),
                        "part": part_index,
                        "parts": len(pieces),
                    }
                )

        logger.save_artifact("chunks_by_title.json", parent_chunks)
        _logger.info("Created %d title-based parent chunks.", len(parent_chunks))
        return parent_chunks
    except Exception as exc:
        _logger.exception("Error creating chunks by title: %s", exc)
        return None


def _safe_metadata(metadata: dict) -> dict:
    """Compact scalar and list metadata on searchable child chunks."""
    safe = {}
    for key, value in metadata.items():
        if value is None or value == "":
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[key] = value
        elif isinstance(value, (list, tuple)):
            flat = [item for item in value if isinstance(item, (str, int, float, bool))]
            if flat:
                safe[key] = flat
    return safe


def build_document_discovery_context(chunks: list[dict]) -> dict:
    """Extract document abstract or create a fallback summary using the first few sections of the document."""
    for chunk in chunks:
        title = " ".join((chunk.get("title") or "").lower().split())
        if title in _ABSTRACT_TITLES:
            abstract = (chunk.get("text") or "").strip()
            if abstract:
                return {"source": "abstract", "text": abstract}

    sections = []
    remaining = _DISCOVERY_SUMMARY_MAX_CHARS
    for chunk in chunks:
        text = (chunk.get("text") or "").strip()
        if not text or remaining <= 0:
            continue
        section = f"## {chunk.get('title', 'Document')}\n{text}"
        sections.append(section[:remaining])
        remaining -= len(section)
    return {"source": "generated", "text": "\n\n".join(sections)}


def _prepare_chunk_images(chunk: dict, reference_counts: Counter):
    candidate_refs = [
        ref
        for ref in chunk.get("image_refs", [])
        if is_meaningful_image(ref, reference_counts)
    ]
    resolved = [(ref, image_data_url(ref)) for ref in candidate_refs]
    return ([ref for ref, url in resolved if url], [url for _, url in resolved if url])


async def add_visual_summaries(
    chunks: list[dict], run_config: RunnableConfig | None = None
) -> list[dict]:
    """Attach visual summary to each source parent chunk.

    All images in a chunk are sent in one request. The resulting summary is stored as a dedicated visual child chunk.
    """
    reference_counts = Counter(
        ref for chunk in chunks for ref in chunk.get("image_refs", [])
    )

    for chunk in chunks:
        retained_refs, image_urls = await run_ingestion_local(
            _prepare_chunk_images, chunk, reference_counts
        )
        if not image_urls:
            continue

        try:
            analysis_json = await enhancer.agenerate_summaries(
                chunk.get("text", ""), image_urls, run_config
            )
            analysis = json.loads(analysis_json) if analysis_json else {}
            visual_summary = str(analysis.get("visual_analysis", "")).strip()
            if visual_summary:
                chunk["visual_summary"] = visual_summary
                chunk["summarized_image_refs"] = retained_refs
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            _logger.warning("Could not summarize images in a chunk: %s", exc)
        except Exception:
            _logger.exception("Unexpected error summarizing images in a chunk")

    return chunks


async def build_retrieval_chunks(
    chunks: list[dict],
    file_metadata: dict,
    run_config: RunnableConfig | None = None,
):
    """Summarize images remotely, then serialize local chunk construction."""
    chunks = await add_visual_summaries(chunks or [], run_config)
    return await run_ingestion_local(_build_retrieval_chunks, chunks, file_metadata)


def _build_retrieval_chunks(chunks: list[dict], file_metadata: dict):
    """Build parent chunks and smaller searchable child chunks."""
    try:
        parent_docs = []
        child_docs = []

        for chunk_order, chunk in enumerate(chunks or [], start=1):
            parent_id = str(uuid.uuid4())
            title = chunk.get("title") or file_metadata.get("doc_title") or "Document"
            text = (chunk.get("text") or "").strip()
            if not text:
                continue

            pages = chunk.get("pages") or []
            parent_metadata = {
                **file_metadata,
                "id": parent_id,
                "parent_id": parent_id,
                "title": title,
                "page": pages,
                "type_chunk": "parent",
                "part": chunk.get("part", 1),
                "parts": chunk.get("parts", 1),
                "heading_level": chunk.get("heading_level", 0),
                "image_refs": chunk.get("image_refs", []),
                "chunk_order": chunk_order,
            }
            parent_doc = Document(
                page_content=text,
                metadata=parent_metadata,
            )
            parent_docs.append((parent_id, parent_doc))

            for child_text in child_text_splitter.split_text(text):
                if not child_text.strip():
                    continue

                parent_image_refs = chunk.get("image_refs", [])
                child_image_refs = image_refs_in_text(child_text)
                child_metadata = _safe_metadata(
                    {
                        **file_metadata,
                        "id": str(uuid.uuid4()),
                        "parent_id": parent_id,
                        "title": title,
                        "page": pages,
                        "type_chunk": "child",
                        "type": "markdown",
                        "part": chunk.get("part", 1),
                        "chunk_order": chunk_order,
                        "image_refs": parent_image_refs or child_image_refs,
                    }
                )
                child_docs.append(
                    Document(page_content=child_text, metadata=child_metadata)
                )

            visual_summary = chunk.get("visual_summary", "")
            if visual_summary:
                visual_text = f"[Visual content]\n{visual_summary}"
                for visual_part, visual_child_text in enumerate(
                    child_text_splitter.split_text(visual_text), start=1
                ):
                    if not visual_child_text.strip():
                        continue
                    visual_metadata = _safe_metadata(
                        {
                            **file_metadata,
                            "id": str(uuid.uuid4()),
                            "parent_id": parent_id,
                            "title": title,
                            "page": pages,
                            "type_chunk": "child",
                            "type": "visual_summary",
                            "part": chunk.get("part", 1),
                            "visual_part": visual_part,
                            "chunk_order": chunk_order,
                            "image_refs": chunk.get("summarized_image_refs", []),
                        }
                    )
                    child_docs.append(
                        Document(
                            page_content=visual_child_text,
                            metadata=visual_metadata,
                        )
                    )

        logger.save_docs_artifact("parent_chunks.json", parent_docs)
        logger.save_docs_artifact("child_chunks.json", child_docs)
        _logger.info(
            "Created %d parents and %d children.", len(parent_docs), len(child_docs)
        )
        return parent_docs, child_docs
    except Exception as exc:
        _logger.exception("Error creating parent-child documents: %s", exc)
        return [], []
