from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import config


def ensure_managed_document(filepath: str | Path) -> Path:
    """Keep originals in uploads so the database and data can move together."""
    path = Path(filepath).resolve()
    upload_root = Path(config.UPLOAD_DIR).resolve()
    if path.parent.parent == upload_root:
        return path
    folder = upload_root / uuid.uuid4().hex
    folder.mkdir(parents=True, exist_ok=False)
    try:
        return Path(shutil.copyfile(path, folder / path.name))
    except OSError:
        shutil.rmtree(folder, ignore_errors=True)
        raise


def document_source_path(filepath: str | Path) -> str:
    """Serialize a source path relative to UPLOAD_DIR."""
    upload_root = Path(config.UPLOAD_DIR).resolve()
    return Path(filepath).resolve().relative_to(upload_root).as_posix()


def resolve_document_source(source_path: str) -> Path:
    """Resolve a relative source path against the upload directory."""
    upload_root = Path(config.UPLOAD_DIR).resolve()
    path = Path(source_path)
    if path.is_absolute():
        raise ValueError("Document source path must be relative")
    resolved = (upload_root / path).resolve()
    if not resolved.is_relative_to(upload_root):
        raise ValueError("Document source path is outside the upload directory")
    return resolved
