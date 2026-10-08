from typing import List
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
from core.storage import vector_store
import config
from hashlib import md5
from langchain_core.runnables import RunnableConfig
from typing import List
from langchain_core.callbacks.manager import adispatch_custom_event
import math
import gc
import torch


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
                    doc_map[doc_id] = doc

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
            for doc in docs:
                query_id = doc.metadata.get("query_id", 0)
                target_query = queries[query_id]
                all_pairs.append([target_query, doc.page_content])
            return all_pairs

        def get_all_to_all_pairs(docs, queries):
            all_pairs = []
            for doc in docs:
                for query in queries:
                    all_pairs.append([query, doc.page_content])
            return all_pairs

        strategy = config.RERANK_STRATEGY.lower()
        if strategy == "one_to_one":
            all_pairs = get_one_to_one_pairs(candidate_docs, queries)
        else:
            all_pairs = get_all_to_all_pairs(candidate_docs, queries)

        cross_encoder = CrossEncoder(
            config.CROSS_ENCODER_MODEL, device=config.CROSS_ENCODER_DEVICE
        )
        raw_scores = cross_encoder.predict(all_pairs)

        doc_scores = []
        if strategy == "one_to_one":
            doc_scores = [float(score) for score in raw_scores]
        elif strategy == "all_to_all":
            num_queries = len(queries)
            for i in range(len(candidate_docs)):
                start_idx = i * num_queries
                end_idx = start_idx + num_queries
                doc_specific_scores = raw_scores[start_idx:end_idx]
                doc_scores.append(float(max(doc_specific_scores)))

        del cross_encoder
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        elif torch.cuda.is_available():
            torch.cuda.empty_cache()

        scored_docs = zip(doc_scores, candidate_docs)
        sorted_docs = sorted(scored_docs, key=lambda x: x[0], reverse=True)

        final_docs = []
        for score, doc in sorted_docs:
            doc.metadata["cross_encoder_score"] = score
            final_docs.append(doc)

        return final_docs
    except Exception as e:
        return candidate_docs


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
            file: str = task.get("target_file", "")

            if not file or file.strip().lower() == "":
                file = None

            chroma_retriever = vector_store.get_retriever(file_filters=[file])

            for query in task_queries:
                queries.append(query)
                docs = await chroma_retriever.ainvoke(input=query, config=run_config)
                for doc in docs:
                    doc.metadata["query_id"] = query_idx
                query_docs_list.append(docs)
                query_idx += 1

        await adispatch_custom_event("fusion_start", {}, config=run_config)
        fused_docs = reciprocal_rank_fusion(query_docs_list)

        await adispatch_custom_event("rerank_start", {}, config=run_config)
        reranked_docs = rerank_documents(fused_docs, queries)

        file_groups = {}
        for doc in reranked_docs:
            score = doc.metadata.get("cross_encoder_score", 0)
            if score >= config.MIN_RELEVANCE_SCORE:
                source_file = doc.metadata.get("source", "unknown")
                if source_file not in file_groups:
                    file_groups[source_file] = []
                file_groups[source_file].append(doc)

        file_weights = {}
        total_relevance_mass = 0

        for file, docs in file_groups.items():
            file_mass = sum(
                max(0, doc.metadata.get("cross_encoder_score", 0)) for doc in docs
            )
            file_weights[file] = file_mass
            total_relevance_mass += file_mass

        final_docs = []

        if total_relevance_mass > 0:
            for file, docs in file_groups.items():
                proportion = file_weights[file] / total_relevance_mass
                allocated_slots = math.ceil(config.RERANK_TOP_K * proportion)
                final_docs.extend(docs[:allocated_slots])

        final_docs.sort(
            key=lambda x: x.metadata.get("cross_encoder_score", 0), reverse=True
        )
        final_docs = final_docs[: config.RERANK_TOP_K]

        reranked_docs.sort(
            key=lambda x: x.metadata.get("cross_encoder_score", 0), reverse=True
        )

        return final_docs, reranked_docs, queries
    except Exception as e:
        return [], [], []
