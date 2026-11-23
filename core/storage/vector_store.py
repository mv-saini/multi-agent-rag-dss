from __future__ import annotations

import asyncio
import json
import logging
from functools import lru_cache
from uuid import UUID

import numpy as np
import psycopg
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_openai import OpenAIEmbeddings
from psycopg.types.json import Jsonb

import config
from core.storage import sql_database
from utils.concurrency import run_ingestion_io, run_ingestion_local, run_ingestion_write

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(
        model=config.OPENAI_EMBEDDING_MODEL,
        dimensions=config.OPENAI_EMBEDDING_DIMENSIONS,
    )


def _vector_literal(values: list[float]) -> str:
    if len(values) != config.OPENAI_EMBEDDING_DIMENSIONS:
        raise ValueError("Embedding dimensions do not match the retrieval schema")
    vector = np.asarray(values, dtype=float)
    if not np.isfinite(vector).all() or not np.any(vector):
        raise ValueError("Embeddings must be finite, nonzero vectors")
    return json.dumps(vector.tolist(), allow_nan=False)


def store_documents(
    parent_docs: list[tuple[str, Document]],
    child_docs: list[Document],
    metadata: dict,
    doc_index: dict,
    batch_size: int = 100,
) -> None:
    """Embed first, then commit metadata and chunks in one transaction."""
    document_id, parents, children = _prepare_document_records(
        parent_docs, child_docs, metadata, batch_size
    )
    embeddings = _embed_children(child_docs, batch_size)
    vectors = _prepare_vectors(embeddings)
    _write_document_records(
        document_id, parents, children, vectors, metadata, doc_index
    )


def _prepare_document_records(parent_docs, child_docs, metadata, batch_size):
    if batch_size < 1 or not parent_docs or not child_docs:
        raise ValueError(
            "A document needs parent and child chunks and a positive batch size"
        )
    document_id = UUID(metadata["document_id"])
    parents = []
    parent_ids = set()
    for parent_id, doc in parent_docs:
        identifier = UUID(parent_id)
        if identifier in parent_ids:
            raise ValueError("Duplicate parent chunk ID")
        if UUID(doc.metadata["document_id"]) != document_id:
            raise ValueError("Parent belongs to a different document")
        if UUID(doc.metadata["id"]) != identifier:
            raise ValueError("Parent key does not match its metadata ID")
        parent_ids.add(identifier)
        parents.append(
            (
                identifier,
                document_id,
                int(doc.metadata["chunk_order"]),
                doc.page_content,
                Jsonb(doc.metadata),
            )
        )

    children = []
    child_ids = set()
    for position, doc in enumerate(child_docs):
        identifier = UUID(doc.metadata["id"])
        parent_id = UUID(doc.metadata["parent_id"])
        if identifier in child_ids:
            raise ValueError("Duplicate child chunk ID")
        if (
            parent_id not in parent_ids
            or UUID(doc.metadata["document_id"]) != document_id
        ):
            raise ValueError("Child does not belong to one of this document's parents")
        child_ids.add(identifier)
        children.append(
            (
                identifier,
                parent_id,
                document_id,
                position,
                doc.page_content,
                Jsonb(doc.metadata),
                config.OPENAI_EMBEDDING_MODEL,
            )
        )

    return document_id, parents, children


def _embed_children(
    child_docs: list[Document],
    batch_size: int,
    embeddings_client: OpenAIEmbeddings | None = None,
):
    if embeddings_client is None:
        embeddings_client = OpenAIEmbeddings(
            model=config.OPENAI_EMBEDDING_MODEL,
            dimensions=config.OPENAI_EMBEDDING_DIMENSIONS,
        )
    vectors = []
    for start in range(0, len(child_docs), batch_size):
        batch = child_docs[start : start + batch_size]
        embeddings = embeddings_client.embed_documents(
            [doc.page_content for doc in batch]
        )
        if len(embeddings) != len(batch):
            raise ValueError(
                "Embedding response does not match the number of child chunks"
            )
        vectors.extend(embeddings)
    return vectors


def _prepare_vectors(embeddings):
    return [_vector_literal(embedding) for embedding in embeddings]


def _write_document_records(
    document_id, parents, children, vectors, metadata, doc_index
):
    if len(vectors) != len(children):
        raise ValueError("Embedding count does not match child chunks")
    with sql_database.get_connection() as conn:
        with conn.transaction():
            conn.execute(
                """INSERT INTO documents (document_id, filename, metadata, doc_index)
                   VALUES (%s, %s, %s, %s)""",
                (document_id, metadata["source"], Jsonb(metadata), Jsonb(doc_index)),
            )
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO parent_chunks
                       (id, document_id, chunk_order, content, metadata)
                       VALUES (%s, %s, %s, %s, %s)""",
                    parents,
                )
                cursor.executemany(
                    """INSERT INTO child_chunks
                       (id, parent_id, document_id, chunk_order, content, metadata,
                        embedding_model, embedding)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                    [(*row, vector) for row, vector in zip(children, vectors)],
                )
    _logger.info(
        "Committed document %s with %d parents and %d children",
        document_id,
        len(parents),
        len(children),
    )


async def astore_documents(
    parent_docs: list[tuple[str, Document]],
    child_docs: list[Document],
    metadata: dict,
    doc_index: dict,
    batch_size: int = 100,
) -> None:
    """Separate local preparation, embedding API waits, and atomic database writes."""
    document_id, parents, children = await run_ingestion_local(
        _prepare_document_records, parent_docs, child_docs, metadata, batch_size
    )
    embeddings_client = await run_ingestion_io(
        OpenAIEmbeddings,
        model=config.OPENAI_EMBEDDING_MODEL,
        dimensions=config.OPENAI_EMBEDDING_DIMENSIONS,
    )
    vectors = []
    for start in range(0, len(child_docs), batch_size):
        embeddings = await run_ingestion_io(
            _embed_children,
            child_docs[start : start + batch_size],
            batch_size,
            embeddings_client,
        )
        vectors.extend(await run_ingestion_local(_prepare_vectors, embeddings))
        del embeddings
    await run_ingestion_write(
        _write_document_records,
        document_id,
        parents,
        children,
        vectors,
        metadata,
        doc_index,
    )


def _document(row) -> Document:
    identifier, document_id, parent_id, content, metadata = row[:5]
    return Document(
        page_content=content,
        metadata={
            **(metadata or {}),
            "id": str(identifier),
            "document_id": str(document_id),
            "parent_id": str(parent_id),
        },
    )


def _document_filter(document_filters: list[str] | None) -> tuple[str, list]:
    if document_filters is None:
        return "", []
    return " AND document_id = ANY(%s::uuid[])", [
        [UUID(item) for item in document_filters]
    ]


def dense_search(
    query: str, document_filters: list[str] | None = None
) -> list[Document]:
    """Fetch cosine-nearest children with pgvector, then apply MMR diversity."""
    if not query.strip() or document_filters == []:
        return []
    if config.RETRIEVAL_K < 1 or config.FETCH_K < 1:
        raise ValueError("Retrieval limits must be positive")
    if not 0 <= config.MMR_LAMBDA <= 1:
        raise ValueError("MMR_LAMBDA must be between zero and one")
    query_embedding = _get_embeddings().embed_query(query)
    vector = _vector_literal(query_embedding)
    scope, parameters = _document_filter(document_filters)
    with sql_database.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, document_id, parent_id, content, metadata,
                      embedding::text, embedding <=> %s::vector AS distance
               FROM child_chunks WHERE embedding_model = %s"""
            + scope
            + " ORDER BY embedding <=> %s::vector, id LIMIT %s",
            [
                vector,
                config.OPENAI_EMBEDDING_MODEL,
                *parameters,
                vector,
                max(config.FETCH_K, config.RETRIEVAL_K),
            ],
        ).fetchall()
    if not rows:
        return []

    # cosine-based maximal marginal relevance (mmr) selection.
    matrix = np.asarray([json.loads(row[5]) for row in rows], dtype=float)
    matrix /= np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-12)
    query_vector = np.asarray(query_embedding, dtype=float)
    query_vector /= np.linalg.norm(query_vector)
    relevance = matrix @ query_vector
    selected = [int(np.argmax(relevance))]
    redundancy = matrix @ matrix[selected[0]]
    while len(selected) < min(config.RETRIEVAL_K, len(rows)):
        scores = config.MMR_LAMBDA * relevance - (1 - config.MMR_LAMBDA) * redundancy
        scores[selected] = -np.inf
        index = int(np.argmax(scores))
        selected.append(index)
        redundancy = np.maximum(redundancy, matrix @ matrix[index])
    documents = []
    for index in selected:
        doc = _document(rows[index])
        doc.metadata["dense_cosine_distance"] = float(rows[index][6])
        documents.append(doc)
    return documents


class PostgresChildRetriever(BaseRetriever):
    document_filters: list[str] | None = None

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        return dense_search(query, self.document_filters)


def get_child_retriever(document_filters: list[str] | None = None) -> BaseRetriever:
    return PostgresChildRetriever(document_filters=document_filters)


def sparse_search(
    query: str, document_filters: list[str] | None = None, k: int | None = None
) -> list[Document]:
    """Rank matching child chunks with pg_search BM25."""
    if not query.strip() or document_filters == []:
        return []
    limit = config.SPARSE_RETRIEVAL_K if k is None else k
    if limit < 1:
        return []
    scope, parameters = _document_filter(document_filters)
    try:
        with sql_database.get_connection() as conn:
            rows = conn.execute(
                """SELECT id, document_id, parent_id, content, metadata, pdb.score(id)
                   FROM child_chunks WHERE content ||| %s"""
                + scope
                + " ORDER BY pdb.score(id) DESC, id LIMIT %s",
                [query, *parameters, limit],
            ).fetchall()
        documents = []
        for row in rows:
            doc = _document(row)
            doc.metadata["sparse_bm25_score"] = float(row[5])
            documents.append(doc)
        return documents
    except psycopg.Error:
        _logger.exception("BM25 search failed; continuing with dense results")
        return []


async def asparse_search(
    query: str, document_filters: list[str] | None = None, k: int | None = None
) -> list[Document]:
    return await asyncio.to_thread(sparse_search, query, document_filters, k)


def get_parent_documents(parent_ids: list[str]) -> list[Document | None]:
    """Return parents in requested order, retaining None for missing IDs."""
    if not parent_ids:
        return []
    identifiers = [UUID(item) for item in parent_ids]
    with sql_database.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, document_id, id AS parent_id, content, metadata
               FROM parent_chunks WHERE id = ANY(%s::uuid[])""",
            (identifiers,),
        ).fetchall()
    by_id = {row[0]: _document(row) for row in rows}
    return [by_id.get(identifier) for identifier in identifiers]


def get_parent_documents_for_document(document_id: str) -> list[Document]:
    with sql_database.get_connection() as conn:
        rows = conn.execute(
            """SELECT id, document_id, id AS parent_id, content, metadata
               FROM parent_chunks WHERE document_id = %s
               ORDER BY chunk_order, id""",
            (UUID(document_id),),
        ).fetchall()
    return [_document(row) for row in rows]
