import asyncio
from starlette.concurrency import run_in_threadpool
import logging
from utils.concurrency import run_reranking
from functools import lru_cache
from typing import List

from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
from core.storage import vector_store
import config
from hashlib import md5
from langchain_core.runnables import RunnableConfig
from langchain_core.callbacks.manager import adispatch_custom_event
import math

_logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_cross_encoder() -> CrossEncoder:
    """Load and cache the reranker"""
    _logger.info(
        "Loading cross-encoder %s on %s...",
        config.CROSS_ENCODER_MODEL,
        config.CROSS_ENCODER_DEVICE,
    )
    return CrossEncoder(config.CROSS_ENCODER_MODEL, device=config.CROSS_ENCODER_DEVICE)


def reciprocal_rank_fusion(
    query_docs_list: list[list[Document]], alpha=config.RRF_ALPHA
):
    """
    Applies Reciprocal Rank Fusion to combine retrieved documents from multiple queries.
    """

    try:
        if not query_docs_list:
            raise ValueError("No documents to fuse.")

        doc_scores = {}
        doc_map = {}
        for docs in query_docs_list:
            for rank, doc in enumerate(docs):
                doc_id = doc.metadata.get(
                    "id", md5(doc.page_content.encode("utf-8")).hexdigest()
                )

                if doc_id not in doc_map:
                    doc_map[doc_id] = doc.model_copy(
                        update={"metadata": {**doc.metadata, "query_ids": []}}
                    )

                # Preserve every retrieving query when fusing.
                query_ids = doc.metadata.get("query_ids") or [
                    doc.metadata.get("query_id", 0)
                ]
                for query_id in query_ids:
                    if query_id not in doc_map[doc_id].metadata["query_ids"]:
                        doc_map[doc_id].metadata["query_ids"].append(query_id)

                score = 1 / (alpha + (rank + 1))
                if doc_id in doc_scores:
                    doc_scores[doc_id] += score
                else:
                    doc_scores[doc_id] = score
        sorted_ids = sorted(
            doc_scores.keys(), key=lambda x: doc_scores[x], reverse=True
        )
        return [doc_map[doc_id] for doc_id in sorted_ids]
    except Exception as e:
        # Fallback to flattening the lists
        return [doc for docs in query_docs_list for doc in docs]


def rerank_documents(candidate_docs: list[Document], queries: List[str]):
    """
    Reranks documents using a CrossEncoder based on their relevance to the generated queries.
    """

    try:

        def get_one_to_one_pairs(docs, queries):
            all_pairs = []
            pair_counts = []
            for doc in docs:
                query_ids = list(
                    dict.fromkeys(
                        doc.metadata.get("query_ids")
                        or [doc.metadata.get("query_id", 0)]
                    )
                )
                for query_id in query_ids:
                    all_pairs.append([queries[query_id], doc.page_content])
                pair_counts.append(len(query_ids))
            return all_pairs, pair_counts

        def get_all_to_all_pairs(docs, queries):
            all_pairs = []
            for doc in docs:
                for query in queries:
                    all_pairs.append([query, doc.page_content])
            return all_pairs

        strategy = config.RERANK_STRATEGY.lower()
        if strategy == "one_to_one":
            all_pairs, pair_counts = get_one_to_one_pairs(candidate_docs, queries)
        else:
            all_pairs = get_all_to_all_pairs(candidate_docs, queries)

        if not all_pairs:
            return []

        raw_scores = _get_cross_encoder().predict(
            all_pairs,
            batch_size=config.RERANK_BATCH_SIZE,
            show_progress_bar=False,
        )

        doc_scores = []
        if strategy == "one_to_one":
            # Each chunk competes using its best match among retrieving queries.
            start_idx = 0
            for pair_count in pair_counts:
                end_idx = start_idx + pair_count
                doc_scores.append(float(max(raw_scores[start_idx:end_idx])))
                start_idx = end_idx
        elif strategy == "all_to_all":
            num_queries = len(queries)
            for i in range(len(candidate_docs)):
                start_idx = i * num_queries
                end_idx = start_idx + num_queries
                doc_specific_scores = raw_scores[start_idx:end_idx]
                doc_scores.append(float(max(doc_specific_scores)))

        scored_docs = zip(doc_scores, candidate_docs)
        sorted_docs = sorted(scored_docs, key=lambda x: x[0], reverse=True)

        final_docs = []
        for score, doc in sorted_docs:
            doc.metadata["cross_encoder_score"] = score
            final_docs.append(doc)

        return final_docs
    except Exception as e:
        _logger.exception("Cross-encoder reranking failed; using vector ranking: %s", e)
        for doc in candidate_docs:
            doc.metadata["cross_encoder_score"] = 1.0
        return candidate_docs


def load_ranked_parents(ranked_children: list[Document]) -> list[Document]:
    """Get the parent chunks corresponding to the child chunks."""
    parent_ids = list(
        dict.fromkeys(
            doc.metadata.get("parent_id")
            for doc in ranked_children
            if doc.metadata.get("parent_id")
        )
    )
    if not parent_ids:
        return []
    parent_by_id = dict(zip(parent_ids, vector_store.get_parent_documents(parent_ids)))

    parents = []
    seen_parent_ids = set()
    for child in ranked_children:
        parent_id = child.metadata.get("parent_id")
        if parent_id in seen_parent_ids:
            continue
        parent = parent_by_id.get(parent_id)
        if parent is None:
            _logger.warning(
                "Missing parent document for child %s", child.metadata.get("id")
            )
            continue
        seen_parent_ids.add(parent_id)

        parent.metadata = {
            **parent.metadata,
            "cross_encoder_score": child.metadata.get("cross_encoder_score", 0.0),
            "matched_child_id": child.metadata.get("id"),
            "matched_child_text": child.page_content,
        }
        parents.append(parent)
    return parents


async def retrieve(vector_tasks: list[dict], run_config: RunnableConfig = None):
    try:
        await adispatch_custom_event(
            "reasoning_header", "Retrieving documents...", config=run_config
        )

        query_docs_list: list[list[Document]] = []
        queries = []
        query_idx = 0

        for task in vector_tasks:
            task_queries: list[str] = task.get("queries", [])
            document_id: str = task.get("target_document_id", "")

            if not document_id or not document_id.strip():
                continue

            child_retriever = vector_store.get_child_retriever(
                document_filters=[document_id]
            )

            for query in task_queries:
                queries.append(query)
                dense_docs = await child_retriever.ainvoke(
                    input=query, config=run_config
                )
                for doc in dense_docs:
                    doc.metadata["query_id"] = query_idx
                query_docs_list.append(dense_docs)

                if config.HYBRID_SEARCH_ENABLED:
                    sparse_docs = await vector_store.asparse_search(
                        query,
                        document_filters=[document_id],
                    )
                    for doc in sparse_docs:
                        doc.metadata["query_id"] = query_idx
                    query_docs_list.append(sparse_docs)
                query_idx += 1

        await adispatch_custom_event("fusion_start", {}, config=run_config)
        fused_docs = await run_in_threadpool(reciprocal_rank_fusion, query_docs_list)

        await adispatch_custom_event("rerank_start", {}, config=run_config)
        reranked_docs = await run_reranking(rerank_documents, fused_docs, queries)

        if config.MIN_RELEVANCE_SCORE is None:
            relevant_children = reranked_docs
        else:
            relevant_children = [
                doc
                for doc in reranked_docs
                if doc.metadata.get("cross_encoder_score", float("-inf"))
                >= config.MIN_RELEVANCE_SCORE
            ]

        document_groups = {}
        for doc in relevant_children:
            source_document_id = doc.metadata.get("document_id", "unknown")
            if source_document_id not in document_groups:
                document_groups[source_document_id] = []
            document_groups[source_document_id].append(doc)

        document_weights = {}
        total_relevance_mass = 0

        for source_document_id, docs in document_groups.items():
            document_mass = sum(
                max(0, doc.metadata.get("cross_encoder_score", 0)) for doc in docs
            )
            document_weights[source_document_id] = document_mass
            total_relevance_mass += document_mass

        selected_children = []

        if total_relevance_mass > 0:
            for source_document_id, docs in document_groups.items():
                proportion = document_weights[source_document_id] / total_relevance_mass
                allocated_slots = math.ceil(config.RERANK_TOP_K * proportion)
                selected_children.extend(docs[:allocated_slots])

        selected_children.sort(
            key=lambda x: x.metadata.get("cross_encoder_score", 0), reverse=True
        )

        selected_ids = {doc.metadata.get("id") for doc in selected_children}
        selected_children.extend(
            doc
            for doc in relevant_children
            if doc.metadata.get("id") not in selected_ids
        )
        final_docs = (await asyncio.to_thread(load_ranked_parents, selected_children))[
            : config.RERANK_TOP_K
        ]

        reranked_docs.sort(
            key=lambda x: x.metadata.get("cross_encoder_score", 0), reverse=True
        )

        return final_docs, reranked_docs, queries
    except Exception as e:
        _logger.exception("Document retrieval failed: %s", e)
        return [], [], []
