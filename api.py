from __future__ import annotations

import os
import logging
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.concurrency import run_in_threadpool

from routers.auth import AuthenticationError, AuthorizationError, auth_router
from core.storage import sql_database
from routers.documents import drain_ingestion_jobs, router as documents_router
from routers.threads import router as threads_router
from routers.users import users_router
from routers.seismic import router as seismic_router
from utils import logger
from utils.concurrency import start_workers, shutdown_workers

load_dotenv()
_logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Release process-level resources when this worker stops."""
    start_workers()
    await run_in_threadpool(logger.setup_logger, "api")
    _logger.info("API logging initialized")
    try:
        yield
    finally:
        try:
            try:
                await drain_ingestion_jobs()
            finally:
                await run_in_threadpool(shutdown_workers)
        finally:
            try:
                await run_in_threadpool(sql_database.close_connection_pool)
            finally:
                await run_in_threadpool(logger.shutdown_logger)


app = FastAPI(title="Backend", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(documents_router)
app.include_router(threads_router)
app.include_router(seismic_router)


def _request_user_identity(request: Request) -> tuple[str | None, str | None]:
    user = getattr(request.state, "authenticated_user", None)
    if not user:
        return None, None
    return user.get("id"), user.get("username")


@app.middleware("http")
async def log_api_request(request: Request, call_next) -> Response:
    """Record concise entry for every HTTP request handled by the API."""
    started_at = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        user_id, username = _request_user_identity(request)
        _logger.exception(
            "%s %s failed user_id=%s username=%r",
            request.method,
            request.url.path,
            user_id,
            username,
        )
        raise

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    user_id, username = _request_user_identity(request)
    _logger.info(
        "%s %s completed with %s in %.1fms user_id=%s username=%r",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
        user_id,
        username,
    )
    return response


@app.exception_handler(AuthenticationError)
async def handle_authentication_error(
    _request: Request, exc: AuthenticationError
) -> Response:
    return Response(status_code=status.HTTP_401_UNAUTHORIZED, content=str(exc))


@app.exception_handler(AuthorizationError)
async def handle_authorization_error(
    _request: Request, exc: AuthorizationError
) -> Response:
    return Response(status_code=status.HTTP_403_FORBIDDEN, content=str(exc))


app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:8080"
    ).split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# uvicorn api:app --reload
