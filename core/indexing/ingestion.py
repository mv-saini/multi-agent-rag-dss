from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from pathlib import Path

from langfuse import get_client
from langchain_core.runnables import RunnableConfig

from core.indexing import enhancer, loader, processor
from core.storage import vector_store
from core.storage.document_files import ensure_managed_document
from utils.concurrency import run_ingestion_io, run_ingestion_local

_logger = logging.getLogger(__name__)

ProgressCallback = Callable[[str, int, str], Awaitable[None] | None]


class IngestionError(RuntimeError):
    """Exception raised when a document cannot be fully indexed."""


def ingest_document(
    filepath: str | Path,
    progress: ProgressCallback | None = None,
    run_config: RunnableConfig | None = None,
) -> dict[str, int | str]:
    """Synchronous entry point for the CLI."""
    return asyncio.run(aingest_document(filepath, progress, run_config))


async def aingest_document(
    filepath: str | Path,
    progress: ProgressCallback | None = None,
    run_config: RunnableConfig | None = None,
) -> dict[str, int | str]:
    """Parse, chunk, index, and register one PDF document."""

    async def report(stage: str, percent: int, message: str) -> None:
        if progress:
            result = progress(stage, percent, message)
            if isawaitable(result):
                await result

    path = Path(filepath)
    if not await run_ingestion_io(path.is_file):
        raise IngestionError(f"File does not exist: {path}")
    try:
        path = await run_ingestion_io(ensure_managed_document, path)
    except OSError as exc:
        raise IngestionError("The original PDF could not be saved in uploads.") from exc

    await report("parsing", 10, "Uploading and parsing the PDF...")
    pages, file_metadata, doc_index = await loader.aload_document(str(path))
    if pages is None or file_metadata is None or doc_index is None:
        raise IngestionError("The document could not be parsed.")
    file_metadata["document_id"] = str(uuid.uuid4())

    await report("chunking", 45, "Creating searchable document sections...")
    chunks_by_title = await run_ingestion_local(processor.create_chunks_by_title, pages)
    del pages
    if chunks_by_title is None:
        raise IngestionError("The parsed document could not be split into sections.")

    await report("enriching", 55, "Creating document discovery metadata...")
    discovery_context = await run_ingestion_local(
        processor.build_document_discovery_context, chunks_by_title
    )
    if discovery_context.get("source") == "abstract":
        file_metadata["discovery_summary"] = {
            "source": "abstract",
            "text": discovery_context["text"],
            "keywords": [],
        }
    else:
        discovery_summary = await enhancer.agenerate_document_discovery_summary(
            discovery_context.get("text", ""), run_config
        )
        if discovery_summary:
            file_metadata["discovery_summary"] = discovery_summary

    await report("building_index", 65, "Building retrieval chunks...")
    parent_docs, child_docs = await processor.build_retrieval_chunks(
        chunks_by_title, file_metadata, run_config
    )
    del chunks_by_title
    if not parent_docs or not child_docs:
        raise IngestionError(
            "No searchable content could be created from this document."
        )

    await report("indexing", 80, "Embedding and saving the document...")
    try:
        await vector_store.astore_documents(
            parent_docs, child_docs, file_metadata, doc_index
        )
    except Exception as exc:
        raise IngestionError("The document could not be saved.") from exc

    try:
        await run_ingestion_io(lambda: get_client().flush())
    except Exception:
        _logger.warning("Unable to flush ingestion traces", exc_info=True)

    await report("complete", 100, "Document indexed successfully.")
    return {
        "document_id": file_metadata["document_id"],
        "filename": file_metadata["source"],
        "parent_chunks": len(parent_docs),
        "child_chunks": len(child_docs),
    }
