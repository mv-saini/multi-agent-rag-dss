import config
import logging
from functools import lru_cache
from threading import Lock
from typing import Any

import psycopg
from psycopg_pool import ConnectionPool

_logger = logging.getLogger(__name__)
_pool_lock = Lock()


@lru_cache(maxsize=1)
def _get_connection_pool() -> ConnectionPool:
    """Create a PostgreSQL connection pool."""
    if config.POSTGRES_POOL_MIN_SIZE < 1:
        raise ValueError("POSTGRES_POOL_MIN_SIZE must be at least 1")
    if config.POSTGRES_POOL_MAX_SIZE < config.POSTGRES_POOL_MIN_SIZE:
        raise ValueError(
            "POSTGRES_POOL_MAX_SIZE must be greater than or equal to "
            "POSTGRES_POOL_MIN_SIZE"
        )

    _logger.info(
        "Creating PostgreSQL connection pool (min=%d, max=%d).",
        config.POSTGRES_POOL_MIN_SIZE,
        config.POSTGRES_POOL_MAX_SIZE,
    )
    return ConnectionPool(
        conninfo=config.get_postgres_dsn(),
        min_size=config.POSTGRES_POOL_MIN_SIZE,
        max_size=config.POSTGRES_POOL_MAX_SIZE,
        timeout=config.POSTGRES_POOL_TIMEOUT_SECONDS,
    )


class _PooledConnectionLease:
    """A wrapper that returns a borrowed connection to its pool."""

    def __init__(self, pool: ConnectionPool, connection: psycopg.Connection):
        self._pool = pool
        self._connection = connection
        self._returned = False

    def close(self) -> None:
        """Rollback unfinished work and release the connection back to the pool."""
        if self._returned:
            return
        try:
            self._connection.rollback()
        except psycopg.Error:
            _logger.warning("Unable to reset PostgreSQL connection before release.")
        finally:
            self._pool.putconn(self._connection)
            self._returned = True

    def __enter__(self) -> "_PooledConnectionLease":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    def __getattr__(self, name: str) -> Any:
        if self._returned:
            raise RuntimeError("This PostgreSQL connection has already been released")
        return getattr(self._connection, name)


def get_connection() -> _PooledConnectionLease:
    """Borrow a PostgreSQL connection."""
    with _pool_lock:
        pool = _get_connection_pool()
    return _PooledConnectionLease(pool, pool.getconn())


def close_connection_pool() -> None:
    """Close the connection pool and release all connections."""
    with _pool_lock:
        if _get_connection_pool.cache_info().currsize:
            pool = _get_connection_pool()
            pool.close()
            _get_connection_pool.cache_clear()


def get_indexed_docs() -> list[dict]:
    """Returns the indexed documents."""
    conn = get_connection()

    try:
        rows = conn.execute("""
            SELECT id, document_id, filename
            FROM documents
            ORDER BY LOWER(filename)
            """).fetchall()

        documents = []
        for row in rows:
            documents.append(
                {
                    "id": row[0],
                    "document_id": str(row[1]),
                    "filename": row[2],
                }
            )

        return documents
    finally:
        conn.close()


def get_indexed_document(record_id: int) -> dict | None:
    """Return the stored metadata for one indexed document."""
    conn = get_connection()

    try:
        row = conn.execute(
            """
            SELECT id, document_id, filename, metadata
            FROM documents
            WHERE id = %s
            """,
            (record_id,),
        ).fetchone()
        if row is None:
            return None

        return {
            "id": row[0],
            "document_id": str(row[1]),
            "filename": row[2],
            "metadata": row[3] or {},
        }
    finally:
        conn.close()


def delete_indexed_document(record_id: int) -> bool:
    """Remove metadata and cascade to parent/child chunks and indexes."""
    conn = get_connection()
    try:
        result = conn.execute("DELETE FROM documents WHERE id = %s", (record_id,))
        conn.commit()
        return result.rowcount == 1
    except psycopg.Error as exc:
        conn.rollback()
        _logger.error("Error deleting document metadata %s: %s", record_id, exc)
        return False
    finally:
        conn.close()
