from typing import Union, Tuple, List
import os
import logging
import json
from datetime import datetime
import config
from langchain_core.documents import Document

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


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
    if not os.path.exists("logs"):
        os.makedirs("logs")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = os.path.join("logs", f"{prefix}_{timestamp}")
    os.makedirs(log_dir, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.log_dir = log_dir
    root_logger.setLevel(logging.DEBUG)

    if not root_logger.handlers:
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        fh_all = logging.FileHandler(os.path.join(log_dir, "execution_all.log"))
        fh_all.setLevel(logging.DEBUG)
        fh_all.setFormatter(formatter)
        root_logger.addHandler(fh_all)

        fh_project = logging.FileHandler(os.path.join(log_dir, "execution_project.log"))
        fh_project.setLevel(logging.DEBUG)
        fh_project.setFormatter(formatter)
        fh_project.addFilter(LogFilter())
        root_logger.addHandler(fh_project)

        if config.CONSOLE_LOGGING:
            ch = logging.StreamHandler()
            ch.setLevel(logging.INFO)
            ch.setFormatter(formatter)
            ch.addFilter(LogFilter())
            root_logger.addHandler(ch)

    root_logger.info("Logging session started in %s", log_dir)
    return root_logger


def save_artifact(filename, data):
    """
    Saves data to a file in the logger's log directory as JSON, Markdown, and plain text.
    """

    logger = logging.getLogger()
    log_dir = getattr(logger, "log_dir", None)
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
