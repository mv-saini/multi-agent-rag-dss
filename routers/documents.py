from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from langfuse.langchain import CallbackHandler
from starlette.concurrency import run_in_threadpool

import config
from routers.auth import _require_authentication
from core.indexing.image_assets import image_asset_path
from core.indexing.ingestion import IngestionError, aingest_document
from core.storage import sql_database, vector_store
from core.storage.document_files import resolve_document_source
from services.sse import EventStream, SSE_HEADERS, encode_sse
from utils import logger

router = APIRouter(prefix="/api")
_logger = logging.getLogger(__name__)


@dataclass
class IngestionJob:
    owner_id: str
    stream: EventStream


_jobs: dict[str, IngestionJob] = {}
_ingestion_tasks: set[asyncio.Task] = set()
_ingestion_slots = asyncio.Semaphore(config.INGESTION_MAX_CONCURRENT_DOCUMENTS)
_COMPLETED_JOB_RETENTION_SECONDS = 60
_ASSET_REFERENCE_RE = re.compile(r"asset://([a-f0-9]{64})")


async def drain_ingestion_jobs() -> None:
    """Let staged jobs finish before their worker pools are shut down."""
    if _ingestion_tasks:
        await asyncio.gather(*list(_ingestion_tasks), return_exceptions=True)


async def _run_ingestion_job(job_id: str, file_path: Path) -> None:
    job = _jobs[job_id].stream
    loop = asyncio.get_running_loop()

    async def report(stage: str, percent: int, message: str) -> None:
        await job.append(
            encode_sse(
                {
                    "type": "ingestion_progress",
                    "stage": stage,
                    "percent": percent,
                    "message": message,
                }
            )
        )

    async def ingest() -> dict:
        run_config = {
            "callbacks": [CallbackHandler(trace_context={"trace_id": job_id})]
        }
        await run_in_threadpool(logger.setup_logger, "ingest")
        with logger.artifact_context(f"ingestion_{job_id}"):
            return await aingest_document(file_path, progress=report, run_config=run_config)

    try:
        await report("queued", 0, "Waiting for an ingestion slot...")
        async with _ingestion_slots:
            result = await ingest()
        await job.append(
            encode_sse(
                {
                    "type": "ingestion_complete",
                    "message": "Document indexed successfully.",
                    "document": result,
                }
            )
        )
    except IngestionError as exc:
        _logger.warning("Document ingestion failed for %s: %s", file_path, exc)
        await job.append(encode_sse({"type": "ingestion_error", "message": str(exc)}))
    except Exception:
        _logger.exception("Unexpected document-ingestion failure for %s", file_path)
        await job.append(
            encode_sse(
                {
                    "type": "ingestion_error",
                    "message": "The document could not be indexed.",
                }
            )
        )
    finally:
        try:
            await job.close()
        finally:
            loop.call_later(_COMPLETED_JOB_RETENTION_SECONDS, _jobs.pop, job_id, None)


def _save_uploaded_document(upload: UploadFile) -> Path | JSONResponse:
    filename = Path((upload.filename or "").replace("\\", "/")).name
    if not filename or Path(filename).suffix.lower() != ".pdf":
        upload.file.close()
        return JSONResponse(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            content={"data": None, "error": "Only PDF files can be ingested."},
        )
    upload_folder = Path(config.UPLOAD_DIR) / uuid.uuid4().hex
    destination = upload_folder / filename
    bytes_written = 0
    try:
        upload_folder.mkdir(parents=True, exist_ok=False)
        with destination.open("wb") as saved_file:
            while chunk := upload.file.read(1024 * 1024):
                bytes_written += len(chunk)
                if bytes_written > config.MAX_UPLOAD_SIZE_BYTES:
                    shutil.rmtree(upload_folder, ignore_errors=True)
                    return JSONResponse(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        content={
                            "data": None,
                            "error": "The PDF is larger than the configured upload limit.",
                        },
                    )
                saved_file.write(chunk)
    except OSError:
        shutil.rmtree(upload_folder, ignore_errors=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"data": None, "error": "Unable to save the uploaded PDF."},
        )
    finally:
        upload.file.close()
    return destination


@router.get("/documents")
def get_documents(
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={"data": sql_database.get_indexed_docs(), "error": None},
    )


@router.post("/documents/ingestions", status_code=status.HTTP_202_ACCEPTED)
async def start_document_ingestion(
    file: UploadFile = File(...),
    _user: dict[str, str] = Depends(_require_authentication),
) -> Response:
    destination = await run_in_threadpool(_save_uploaded_document, file)
    if isinstance(destination, JSONResponse):
        return destination
    job_id = uuid.uuid4().hex
    _jobs[job_id] = IngestionJob(owner_id=_user["id"], stream=EventStream())
    task = asyncio.create_task(_run_ingestion_job(job_id, destination))
    _ingestion_tasks.add(task)
    task.add_done_callback(_ingestion_tasks.discard)
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "data": {"job_id": job_id, "filename": destination.name},
            "error": None,
        },
    )


@router.get("/documents/ingestions/{job_id}/events")
async def stream_document_ingestion(
    job_id: str, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    job = _jobs.get(job_id)
    if job is None or job.owner_id != _user["id"]:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"data": None, "error": "Ingestion job not found."},
        )
    return StreamingResponse(
        job.stream.subscribe(), media_type="text/event-stream", headers=SSE_HEADERS
    )


def _remove_managed_upload(source_path: str, filename: str) -> None:
    try:
        upload_root, file_path = (
            Path(config.UPLOAD_DIR).resolve(),
            resolve_document_source(source_path),
        )
        if file_path.name == filename and file_path.parent.parent == upload_root:
            shutil.rmtree(file_path.parent)
    except (OSError, ValueError):
        _logger.warning("Unable to remove managed upload %s", source_path)


@router.delete("/documents/{document_id}")
def delete_document(
    document_id: int, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    document = sql_database.get_indexed_document(document_id)
    if document is None:
        return JSONResponse(
            status_code=404, content={"data": None, "error": "Document not found."}
        )
    if not sql_database.delete_indexed_document(document_id):
        return JSONResponse(
            status_code=500,
            content={
                "data": None,
                "error": "The document could not be deleted.",
            },
        )
    if isinstance(source_path := document["metadata"].get("source_path"), str):
        _remove_managed_upload(source_path, document["filename"])
    return JSONResponse(
        status_code=200, content={"data": {"id": document_id}, "error": None}
    )


@router.get("/documents/{document_id}/file")
def get_document_file(
    document_id: int, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    document = sql_database.get_indexed_document(document_id)
    if document is None:
        return JSONResponse(
            status_code=404, content={"data": None, "error": "Document not found."}
        )
    source_path = document["metadata"].get("source_path")
    if not isinstance(source_path, str) or not source_path:
        return JSONResponse(
            status_code=404,
            content={
                "data": None,
                "error": "The original file is not available for this document.",
            },
        )
    try:
        file_path = resolve_document_source(source_path)
    except (OSError, ValueError):
        file_path = None
    if (
        file_path is None
        or file_path.name != document["filename"]
        or not file_path.is_file()
    ):
        return JSONResponse(
            status_code=404,
            content={
                "data": None,
                "error": "The original file is no longer available at its indexed location.",
            },
        )
    return FileResponse(
        file_path,
        media_type="application/pdf",
        filename=document["filename"],
        content_disposition_type="inline",
    )


@router.get("/documents/{document_id}/parsed")
def get_parsed_document(
    document_id: int, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    document = sql_database.get_indexed_document(document_id)
    if document is None:
        return JSONResponse(
            status_code=404, content={"data": None, "error": "Document not found."}
        )
    chunks = vector_store.get_parent_documents_for_document(document["document_id"])
    if not chunks:
        return JSONResponse(
            status_code=404,
            content={
                "data": None,
                "error": "No parsed content is available for this document.",
            },
        )
    markdown = "\n\n".join(chunk.page_content for chunk in chunks)
    markdown = _ASSET_REFERENCE_RE.sub(
        lambda match: f"/api/images/{match.group(1)}", markdown
    )
    return JSONResponse(
        status_code=200,
        content={
            "data": {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "markdown": markdown,
            },
            "error": None,
        },
    )


@router.get("/images/{asset_id}")
def get_parsed_image(
    asset_id: str, _user: dict[str, str] = Depends(_require_authentication)
) -> Response:
    image_path = image_asset_path(asset_id)
    if image_path is None:
        return JSONResponse(
            status_code=404, content={"data": None, "error": "Image not found."}
        )
    return FileResponse(image_path)
