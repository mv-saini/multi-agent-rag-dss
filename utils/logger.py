from typing import Union, Tuple, List
from contextlib import contextmanager
from contextvars import ContextVar
import os
import logging
import atexit
from logging.handlers import QueueHandler, QueueListener
from queue import SimpleQueue
from threading import Lock
import json
from datetime import datetime
import config
from langchain_core.documents import Document

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_MANAGED_HANDLER_ATTRIBUTE = "_project_logger_handler"
_logging_lock = Lock()
_listener: QueueListener | None = None
_artifact_directory: ContextVar[str | None] = ContextVar(
    "artifact_directory", default=None
)


class LogFilter(logging.Filter):
    """
    Dynamically filters logs based on file path. Keeps logs from project files,
    but drops logs from third-party libraries and virtual environments.
    """

    def filter(self, record):
        path = record.pathname

        # Filter out venv or installed packages
        if (
            "site-packages" in path
            or "dist-packages" in path
            or ".venv" in path
            or "venv" in path
        ):
            return False

        # Keep project logs
        if path.startswith(PROJECT_ROOT):
            return True

        # Deafult, filter out everything else
        return False


def setup_logger(prefix="run"):
    with _logging_lock:
        return _setup_logger(prefix)


def _setup_logger(prefix):
    global _listener
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Check if the logger has already been set up to avoid duplicate handlers
    if any(
        getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False)
        for handler in root_logger.handlers
    ):
        return root_logger

    log_root = os.path.join(PROJECT_ROOT, "logs")
    os.makedirs(log_root, exist_ok=True)
    if prefix == "api":
        log_dir = os.path.join(log_root, "api")
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_dir = os.path.join(log_root, f"{prefix}_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)
    root_logger.log_dir = log_dir

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    fh_project = logging.FileHandler(os.path.join(log_dir, "execution_project.log"))
    fh_project.setLevel(logging.DEBUG)
    fh_project.setFormatter(formatter)
    fh_project.addFilter(LogFilter())
    setattr(fh_project, _MANAGED_HANDLER_ATTRIBUTE, True)
    handlers = [fh_project]

    if config.CONSOLE_LOGGING:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        ch.addFilter(LogFilter())
        setattr(ch, _MANAGED_HANDLER_ATTRIBUTE, True)
        handlers.append(ch)

    queue = SimpleQueue()
    queue_handler = QueueHandler(queue)
    setattr(queue_handler, _MANAGED_HANDLER_ATTRIBUTE, True)
    _listener = QueueListener(queue, *handlers, respect_handler_level=True)
    _listener.start()
    root_logger.addHandler(queue_handler)
    root_logger.info("Logging session started in %s", log_dir)
    return root_logger


def shutdown_logger() -> None:
    """Drain queued records and close managed handlers from a worker thread."""
    global _listener
    with _logging_lock:
        if _listener is None:
            return
        root_logger = logging.getLogger()
        for handler in list(root_logger.handlers):
            if getattr(handler, _MANAGED_HANDLER_ATTRIBUTE, False):
                root_logger.removeHandler(handler)
                handler.close()
        _listener.stop()
        for handler in _listener.handlers:
            handler.close()
        _listener = None
        if hasattr(root_logger, "log_dir"):
            del root_logger.log_dir


atexit.register(shutdown_logger)


@contextmanager
def artifact_context(name: str):
    """Store artifacts in an isolated subdirectory."""
    root_logger = logging.getLogger()
    log_dir = getattr(root_logger, "log_dir", None)
    if not log_dir:
        yield
        return

    safe_name = "".join(
        character if character.isalnum() or character in {"-", "_"} else "_"
        for character in name
    )
    directory = os.path.join(log_dir, "artifacts", safe_name or "run")
    os.makedirs(directory, exist_ok=True)
    token = _artifact_directory.set(directory)
    try:
        yield directory
    finally:
        _artifact_directory.reset(token)


def save_artifact(filename, data):
    """
    Saves data to a file in the logger's log directory as JSON, Markdown, and plain text.
    """

    logger = logging.getLogger()
    log_dir = _artifact_directory.get() or getattr(logger, "log_dir", None)
    if not log_dir:
        return
    filepath = os.path.join(log_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        if filename.endswith(".json"):
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
        elif filename.endswith((".md", ".txt")):
            if isinstance(data, str):
                f.write(data)
            else:
                f.write(str(data))
        else:
            if isinstance(data, str):
                f.write(data)
            else:
                json.dump(data, f, indent=2, ensure_ascii=False)
    logger.info("Saved artifact to %s", filepath)


def doc_to_dict(item: Union[Document, Tuple[str, Document]]):
    """
    Converts a langchain Document or a (id, Document) tuple into a dictionary.
    Dynamically handles metadata for both Parent and Child documents.
    """

    # If the item is a Parent tuple (id, Document), extract just the Document
    if isinstance(item, tuple) and len(item) == 2:
        _, doc = item
    else:
        doc = item

    metadata = getattr(doc, "metadata", {})

    return {
        "page_content": getattr(doc, "page_content", getattr(doc, "text", str(doc))),
        "metadata": metadata,
    }


def save_docs_artifact(
    filename: str, docs: Union[List[Document], List[Tuple[str, Document]]]
):
    """
    Saves a list of Documents or (id, Document) tuples to a JSON artifact.
    """

    data = [doc_to_dict(doc) for doc in docs]
    save_artifact(filename, data)
