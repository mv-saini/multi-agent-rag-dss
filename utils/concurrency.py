"""Dedicated workers for synchronous application jobs."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from functools import partial
from threading import Lock
from typing import Callable, ParamSpec, TypeVar
import config

P = ParamSpec("P")
T = TypeVar("T")
_executors: dict[str, ThreadPoolExecutor] = {}
_executor_lock = Lock()
_accepting_jobs = True


def start_workers() -> None:
    """Allow lazy worker creation when the application lifespan starts."""
    global _accepting_jobs
    with _executor_lock:
        _accepting_jobs = True


async def _run_worker(
    name: str,
    max_workers: int,
    function: Callable[P, T],
    *args: P.args,
    **kwargs: P.kwargs
) -> T:
    with _executor_lock:
        if not _accepting_jobs:
            raise RuntimeError("Application workers are shutting down")
        executor = _executors.get(name)
        if executor is None:
            executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix=name
            )
            _executors[name] = executor
        call = partial(function, *args, **kwargs)
        future = executor.submit(copy_context().run, call)
    return await asyncio.wrap_future(future)


async def run_spatial(function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    """Limit heavy spatial analysis to one active job."""
    return await _run_worker("spatial", 1, function, *args, **kwargs)


async def run_reranking(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Limit reranking to one active job."""
    return await _run_worker("reranking", 1, function, *args, **kwargs)


async def run_ingestion_io(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Run synchronous ingestion API calls and downloads."""
    return await _run_worker(
        "ingestion_io",
        config.INGESTION_MAX_CONCURRENT_DOCUMENTS,
        function,
        *args,
        **kwargs
    )


async def run_ingestion_local(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Limit local ingestion preparation to one active job."""
    return await _run_worker("ingestion_local", 1, function, *args, **kwargs)


async def run_ingestion_write(
    function: Callable[P, T], *args: P.args, **kwargs: P.kwargs
) -> T:
    """Limit ingestion database writes to one active job."""
    return await _run_worker("ingestion_write", 1, function, *args, **kwargs)


def shutdown_workers() -> None:
    """Drain running jobs and cancel queued jobs; call from a worker thread."""
    global _accepting_jobs
    with _executor_lock:
        _accepting_jobs = False
        executors = list(_executors.values())
        _executors.clear()
    for executor in executors:
        executor.shutdown(wait=True, cancel_futures=True)
