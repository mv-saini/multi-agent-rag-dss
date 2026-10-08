import sqlite3
import json
import config
import os
import logging

_logger = logging.getLogger(__name__)


def get_connection():
    db_path = config.SQLITE_DB_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    return conn


def initialize_schema():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS document_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE,
            metadata JSON,
            doc_index JSON
        )
    """)
    conn.commit()
    conn.close()


def store_document_metadata(metadata: dict, doc_index: dict):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        filename = metadata.get("source", "N/A")
        cursor.execute(
            """
            INSERT INTO document_metadata (filename, metadata, doc_index)
            VALUES (?, ?, ?)
            ON CONFLICT(filename) DO UPDATE SET
            metadata=excluded.metadata, doc_index=excluded.doc_index
        """,
            (filename, json.dumps(metadata), json.dumps(doc_index)),
        )
        conn.commit()
        _logger.info(f"{filename} stored successfully in SQLite.")
    except Exception as e:
        _logger.error(f"Error storing {filename} in SQLite: {e}")
    finally:
        conn.close()


def get_indexed_docs() -> list[dict]:
    """Returns the indexed documents."""
    conn = get_connection()
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute("""
            SELECT id, filename
            FROM document_metadata
            ORDER BY filename COLLATE NOCASE
            """).fetchall()

        documents = []
        for row in rows:
            documents.append(
                {
                    "id": row["id"],
                    "filename": row["filename"],
                }
            )

        return documents
    finally:
        conn.close()
