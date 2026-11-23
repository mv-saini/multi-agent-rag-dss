from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
import tempfile
import urllib.request
from collections import Counter
from collections.abc import Mapping
from typing import Any
from pathlib import Path
from urllib.parse import unquote, urlparse

import config
from PIL import Image

_MARKDOWN_IMAGE_RE = re.compile(r'(!\[[^\]]*\]\s*\\?\()([^\s)]+)(\s*(?:"[^"]*")?\))')
_HTML_IMAGE_RE = re.compile(r'(<img\b[^>]*?\bsrc=["\'])([^"\']+)(["\'][^>]*>)', re.I)
_ASSET_RE = re.compile(r"asset://([a-f0-9]{64})")
_MIN_IMAGE_DIMENSION = 96
_MIN_IMAGE_AREA = 12_000
_MAX_DECORATIVE_ASPECT_RATIO = 8


def _asset_dir() -> Path:
    """Return the folder where asset:// references are stored."""
    return Path(config.IMAGE_STORE_DIR)


def _image_mime(raw: bytes, declared_mime: str | None = None) -> str:
    """Return a usable image MIME type, by checking the magic bytes of the file"""
    declared = (declared_mime or "").split(";", 1)[0].lower()
    if declared.startswith("image/"):
        return declared
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        return "image/webp"
    return declared or "application/octet-stream"


def _save_bytes(raw: bytes, mime: str | None = None) -> str:
    """Save bytes to the local asset store and return an asset://<sha256> reference."""
    digest = hashlib.sha256(raw).hexdigest()
    folder = _asset_dir()
    folder.mkdir(parents=True, exist_ok=True)
    suffix = mimetypes.guess_extension(_image_mime(raw, mime)) or ".bin"
    path = folder / f"{digest}{suffix}"
    if not path.exists():
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=folder, prefix=".image-", delete=False
            ) as saved:
                temporary_path = Path(saved.name)
                saved.write(raw)
            temporary_path.replace(path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
    return f"asset://{digest}"


def _as_dict(value: Any) -> dict[str, Any]:
    """Convert a value to a dictionary, if possible."""
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return value.model_dump(mode="json", exclude_none=True)
        except TypeError:
            return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    return {}


def image_source_map(parse_result: Any) -> dict[str, str]:
    """Map LlamaParse's Markdown relative filenames to their temporary download URLs in ``images_content_metadata.images``.

    Example: ``page_1_image_1_v2.jpg": "https://temporary-signed-url...``
    """
    result = _as_dict(parse_result)
    metadata = _as_dict(result.get("images_content_metadata"))
    images = metadata.get("images", [])
    sources: dict[str, str] = {}
    for image in images if isinstance(images, list) else []:
        image_data = _as_dict(image)
        filename = image_data.get("filename") or image_data.get("name")
        url = (
            image_data.get("presigned_url")
            or image_data.get("url")
            or image_data.get("download_url")
        )
        if isinstance(filename, str) and isinstance(url, str):
            sources[filename] = url
            sources[unquote(filename)] = url
            sources[Path(unquote(filename)).name] = url
    return sources


def _materialize_url(url: str, sources: Mapping[str, str] | None = None) -> str:
    """Download a URL or data URL and return a durable asset:// reference."""
    if url.startswith("asset://"):
        return url

    if sources:
        source_url = sources.get(url) or sources.get(unquote(url))
        source_url = source_url or sources.get(Path(urlparse(url).path).name)
        if source_url:
            url = source_url
    if url.startswith("data:"):
        header, payload = url.split(",", 1)
        mime = header[5:].split(";", 1)[0] or "application/octet-stream"
        raw = (
            base64.b64decode(payload)
            if ";base64" in header
            else unquote(payload).encode("utf-8")
        )
        return _save_bytes(raw, mime)
    if url.startswith(("http://", "https://")):
        request = urllib.request.Request(
            url, headers={"User-Agent": "RAG-image-ingestion/1.0"}
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            mime = response.headers.get_content_type()
        return _save_bytes(raw, mime)
    return url


def materialize_markdown_images(
    markdown: str, sources: Mapping[str, str] | None = None
) -> tuple[str, list[str]]:
    """
    Replace Markdown/HTML image URLs with durable local asset:// references.

    Example: ``markdown = "![map](page_1_image_1_v2.jpg)"`` => ``markdown = "![map](asset://9c074039...)"``, ``image_refs = ["asset://9c074039..."]``
    """
    refs: list[str] = []

    def replace(match):
        original = match.group(2)
        try:
            ref = _materialize_url(original, sources)
        except Exception:
            # Preserve the original URL if it cannot be downloaded
            ref = original
        if ref.startswith("asset://"):
            refs.append(ref)
        return match.group(1) + ref + match.group(3)

    markdown = _MARKDOWN_IMAGE_RE.sub(replace, markdown)

    def replace_html(match):
        original = match.group(2)
        try:
            ref = _materialize_url(original, sources)
        except Exception:
            ref = original
        if ref.startswith("asset://"):
            refs.append(ref)
        return match.group(1) + ref + match.group(3)

    markdown = _HTML_IMAGE_RE.sub(replace_html, markdown)

    for match in _ASSET_RE.finditer(markdown):
        ref = match.group(0)
        if ref not in refs:
            refs.append(ref)
    return markdown, list(dict.fromkeys(refs))


def image_data_url(asset_ref: str) -> str | None:
    """
    Resolve an asset:// reference to a data URL for a multimodal LLM.

    Example: data:image/png;base64,base64-encoded-bytes
    """
    match = _ASSET_RE.fullmatch(asset_ref or "")
    if not match:
        if (asset_ref or "").startswith("data:image/"):
            return asset_ref
        return None
    digest = match.group(1)
    folder = _asset_dir()
    paths = list(folder.glob(f"{digest}.*")) if folder.exists() else []
    if not paths:
        return None
    path = paths[0]
    raw = path.read_bytes()
    mime = _image_mime(raw, mimetypes.guess_type(path.name)[0])
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def image_asset_path(asset_id: str) -> Path | None:
    """Return the locally stored image path for a SHA-256 asset ID."""
    if not re.fullmatch(r"[a-f0-9]{64}", asset_id or ""):
        return None
    folder = _asset_dir()
    paths = list(folder.glob(f"{asset_id}.*")) if folder.exists() else []
    return paths[0] if paths and paths[0].is_file() else None


def is_meaningful_image(asset_ref: str, reference_counts: Mapping[str, int]) -> bool:
    """Return whether an image is worth including in a multimodal LLM request.

    Repeated, tiny, and extremely wide or tall assets (logos, footer icons, and rules).
    """
    if reference_counts[asset_ref] > 1:
        return False

    path = image_asset_path(asset_ref.removeprefix("asset://"))
    if path is None:
        return False

    try:
        with Image.open(path) as image:
            width, height = image.size
    except (OSError, ValueError):
        return False

    if width < _MIN_IMAGE_DIMENSION or height < _MIN_IMAGE_DIMENSION:
        return False
    if width * height < _MIN_IMAGE_AREA:
        return False

    aspect_ratio = width / height
    return (
        1 / _MAX_DECORATIVE_ASPECT_RATIO <= aspect_ratio <= _MAX_DECORATIVE_ASPECT_RATIO
    )


def meaningful_image_refs(image_refs: list[str]) -> list[str]:
    """Filter image references."""
    reference_counts = Counter(image_refs)
    return [ref for ref in image_refs if is_meaningful_image(ref, reference_counts)]


def image_refs_in_text(text: str) -> list[str]:
    """Return durable asset references occurring in a chunk's Markdown."""
    return list(
        dict.fromkeys(match.group(0) for match in _ASSET_RE.finditer(text or ""))
    )


def multimodal_message_content(
    text: str, image_refs: list[str] | None = None
) -> list[dict]:
    """Build text and image content blocks for common LangChain/OpenAI-style multimodal messages."""
    content: list[dict] = [{"type": "text", "text": text}]
    for ref in image_refs or image_refs_in_text(text):
        data_url = image_data_url(ref)
        if data_url:
            content.append({"type": "image_url", "image_url": {"url": data_url}})
    return content
