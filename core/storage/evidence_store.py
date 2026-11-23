from __future__ import annotations

import base64
import gzip
import hashlib
import json
from typing import Any

from langchain_core.documents import Document
from psycopg.types.json import Jsonb

from core.storage import sql_database

_COMPRESS_AFTER_BYTES = 1024 * 1024
_ENCODING = "gzip+base64"


def _storage_payload(serialized: str) -> dict[str, Any]:
    raw = serialized.encode("utf-8")
    if len(raw) < _COMPRESS_AFTER_BYTES:
        return json.loads(serialized)
    return {
        "_evidence_encoding": _ENCODING,
        "version": 1,
        "data": base64.b64encode(gzip.compress(raw, compresslevel=6, mtime=0)).decode(
            "ascii"
        ),
    }


def _restore_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if "_evidence_encoding" not in payload:
        return payload
    if payload["_evidence_encoding"] != _ENCODING or payload.get("version") != 1:
        raise ValueError("Unsupported evidence storage encoding")
    return json.loads(gzip.decompress(base64.b64decode(payload["data"], validate=True)))


def empty_bundle() -> dict[str, Any]:
    return {
        "context": {"vector_docs": [], "web_results": [], "spatial_analysis": []},
        "map_layers": [],
        "citation_sources": {},
    }


def _json_default(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    raise TypeError(f"Unsupported evidence value: {type(value).__name__}")


def save(thread_id: str, execution_id: str, bundle: dict[str, Any]) -> str:
    prefix = f"{execution_id}:"
    payload = {
        **bundle,
        "map_layers": [
            {
                **layer,
                **{
                    key: value if value.startswith(prefix) else prefix + value
                    for key in ("scenario_group", "geojson_source")
                    if (value := layer.get(key))
                },
                "layer_id": (
                    layer["layer_id"]
                    if layer["layer_id"].startswith(prefix)
                    else prefix + layer["layer_id"]
                ),
            }
            for layer in bundle["map_layers"]
        ],
    }
    serialized = json.dumps(
        payload,
        default=_json_default,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )
    identity = json.dumps([thread_id, execution_id, serialized], ensure_ascii=False)
    bundle_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    del identity
    storage_payload = _storage_payload(serialized)
    del serialized
    with sql_database.get_connection() as conn:
        conn.execute(
            """INSERT INTO evidence_bundles (id, thread_id, execution_id, payload)
               VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING""",
            (bundle_id, thread_id, execution_id, Jsonb(storage_payload)),
        )
        conn.commit()
    return bundle_id


def load(bundle_id: str | None, thread_id: str | None = None) -> dict[str, Any]:
    if not bundle_id:
        return empty_bundle()
    with sql_database.get_connection() as conn:
        row = conn.execute(
            """SELECT payload FROM evidence_bundles
               WHERE id = %s AND (%s::text IS NULL OR thread_id = %s)""",
            (bundle_id, thread_id, thread_id),
        ).fetchone()
        conn.commit()
    if row is None:
        raise LookupError("Evidence bundle not found.")
    bundle = _restore_payload(row[0])
    bundle["context"]["vector_docs"] = [
        Document(**document) for document in bundle["context"].get("vector_docs", [])
    ]
    return bundle
