from __future__ import annotations

import re
import logging
import os
from pathlib import Path
from typing import Any

from llama_cloud import LlamaCloud
from pypdf import PdfReader

from utils import logger
from core.indexing.image_assets import image_source_map, materialize_markdown_images
from core.storage.document_files import document_source_path
from utils.concurrency import run_ingestion_io, run_ingestion_local

_logger = logging.getLogger(__name__)


def extract_metadata(filepath: str) -> dict:
    """Extract basic PDF metadata locally"""
    try:
        reader = PdfReader(filepath)
        meta = reader.metadata
        cleaned = {}
        if meta:
            for key, value in meta.items():
                clean_key = str(key).strip("/").lower()
                if value is not None:
                    cleaned[f"doc_{clean_key}"] = str(value)
        return cleaned
    except Exception as exc:
        _logger.warning("Could not extract PDF metadata: %s", exc)
        return {}


def _as_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", exclude_none=True)
        except TypeError:
            return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def _get_markdown_pages(result: Any, materialize_images: bool = True) -> list[dict]:
    """Normalize LlamaParse's Markdown response."""

    image_sources = image_source_map(result)
    markdown = getattr(result, "markdown", None)
    if markdown is None:
        payload = _as_dict(result)
        markdown = payload.get("markdown")

    md_dict = _as_dict(markdown)
    pages = getattr(markdown, "pages", None)
    if pages is None:
        pages = md_dict.get("pages", []) if md_dict else []

    normalized = []
    for index, page in enumerate(pages or [], start=1):
        page_dict = _as_dict(page)
        text = getattr(page, "markdown", None)
        if text is None:
            text = page_dict.get("markdown") or page_dict.get("text") or ""
        page_number = (
            getattr(page, "page_number", None) or page_dict.get("page_number") or index
        )
        try:
            page_number = int(page_number)
        except (TypeError, ValueError):
            page_number = index
        if text and str(text).strip():
            markdown_text, image_refs = (
                materialize_markdown_images(str(text).strip(), image_sources)
                if materialize_images
                else (str(text).strip(), [])
            )
            normalized.append(
                {
                    "page_number": page_number,
                    "markdown": markdown_text,
                    "image_refs": image_refs,
                }
            )

    # If full Markdown was returned as a string rather than pages.
    if not normalized:
        full_text = getattr(result, "markdown_full", None) or getattr(
            result, "text", None
        )
        if full_text is None:
            full_text = (
                markdown
                if isinstance(markdown, str)
                else (md_dict.get("markdown") or md_dict.get("text") or "")
            )
        if isinstance(full_text, str) and full_text.strip():
            markdown_text, image_refs = (
                materialize_markdown_images(full_text.strip(), image_sources)
                if materialize_images
                else (full_text.strip(), [])
            )
            normalized.append(
                {"page_number": 1, "markdown": markdown_text, "image_refs": image_refs}
            )

    return normalized


def request_parse(file_path: str):
    """Upload and wait for LlamaParse without holding the local processing worker."""
    _logger.info("Uploading PDF to LlamaParse: %s", file_path)

    # Requires LLAMA_CLOUD_API_KEY in the environment.
    with LlamaCloud(base_url="https://api.cloud.eu.llamaindex.ai") as client:
        uploaded_file = client.files.create(file=file_path, purpose="parse")

        return client.parsing.parse(
            file_id=uploaded_file.id,
            tier="agentic",
            version="latest",
            output_options={
                "markdown": {
                    "inline_images": True,
                    "tables": {"merge_continued_tables": True},
                },
                "images_to_save": ["embedded", "layout"],
            },
            processing_options={"cost_optimizer": {"enable": True}},
            expand=["markdown", "images_content_metadata", "items"],
        )


def partition_document(file_path: str) -> list[dict] | None:
    """Upload and parse a PDF using LlamaParse."""
    try:
        result = request_parse(file_path)
        pages = _get_markdown_pages(result)
        if not pages:
            raise RuntimeError("LlamaParse completed but returned no Markdown pages.")

        try:
            result_dict = _as_dict(result)
            logger.save_artifact("llamaparse_result.json", result_dict)
        except Exception as artifact_exc:
            _logger.debug("Could not save raw LlamaParse response: %s", artifact_exc)

        logger.save_artifact("partitioned_elements.json", pages)
        _logger.info("LlamaParse returned Markdown for %d pages.", len(pages))
        return pages
    except Exception as exc:
        _logger.exception("LlamaParse failed for %s: %s", file_path, exc)
        return None


def build_document_index(pages: list[dict]) -> dict:
    """Build a title index from Markdown headings, retaining page numbers."""

    doc_index = {}
    index = 1
    for page in pages:
        for line in page.get("markdown", "").splitlines():
            match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line.strip())
            if match:
                doc_index[index] = {
                    "title": match.group(1).strip(),
                    "page_number": page.get("page_number", "N/A"),
                }
                index += 1

    logger.save_artifact("doc_index.json", doc_index)
    _logger.info("Document index created with %d Markdown headings.", len(doc_index))
    return doc_index


def _document_metadata(filepath: str, pages: list[dict]):
    file_metadata = extract_metadata(filepath)
    doc_index = build_document_index(pages)
    if not file_metadata.get("doc_title") or file_metadata.get(
        "doc_title", ""
    ).strip() in {"", "N/A"}:
        first_title = next((entry["title"] for entry in doc_index.values()), None)
        file_metadata["doc_title"] = first_title or Path(filepath).stem

    file_metadata["source"] = os.path.basename(filepath)
    file_metadata["source_path"] = document_source_path(filepath)
    file_metadata["parser"] = "llamaparse"
    return pages, file_metadata, doc_index


def load_document(filepath: str):
    """Return page Markdown, source metadata, and a heading index for a PDF file, or None on failure."""
    try:
        pages = partition_document(filepath)
        if pages is None:
            raise RuntimeError("Failed to parse document with LlamaParse.")

        return _document_metadata(filepath, pages)
    except Exception as exc:
        _logger.exception("Error during ingestion: %s", exc)
        return None, None, None


def _materialize_pages(pages: list[dict], sources: dict) -> list[dict]:
    for page in pages:
        page["markdown"], page["image_refs"] = materialize_markdown_images(
            page["markdown"], sources
        )
    return pages


def _prepare_parsed_pages(result):
    try:
        logger.save_artifact("llamaparse_result.json", _as_dict(result))
    except Exception as exc:
        _logger.debug("Could not save raw LlamaParse response: %s", exc)
    return _get_markdown_pages(result, materialize_images=False), image_source_map(
        result
    )


def _finish_document(filepath: str, pages: list[dict]):
    logger.save_artifact("partitioned_elements.json", pages)
    return _document_metadata(filepath, pages)


async def aload_document(filepath: str):
    try:
        result = await run_ingestion_io(request_parse, filepath)
        pages, sources = await run_ingestion_local(_prepare_parsed_pages, result)
        del result
        if not pages:
            raise RuntimeError("LlamaParse completed but returned no Markdown pages.")

        pages = await run_ingestion_io(_materialize_pages, pages, sources)
        return await run_ingestion_local(_finish_document, filepath, pages)
    except Exception:
        _logger.exception("Error during ingestion: %s", filepath)
        return None, None, None
