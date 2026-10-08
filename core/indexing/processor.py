import json
from langchain_classic.text_splitter import RecursiveCharacterTextSplitter
import uuid
from unstructured.chunking.title import chunk_by_title
from langchain_core.documents import Document
from unstructured.documents.elements import Element
from utils import logger
import config
from core.indexing import enhancer
from models.core import ContentData
import logging
import asyncio

_logger = logging.getLogger(__name__)


child_text_splitter = RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=150)


def create_chunks_by_title(elements: list[Element]):
    """
    Creates chunks by title using unstructured lib.
    """

    try:
        _logger.info("Creating chunks by title...")
        chunks = chunk_by_title(
            elements,
            max_characters=config.MAX_CHARACTERS,
            new_after_n_chars=config.NEW_AFTER_N_CHARS,
            combine_text_under_n_chars=config.COMBINE_TEXT_UNDER_N_CHARS,
        )

        _logger.info("Total chunks created: %d", len(chunks))
        logger.save_artifact(
            "chunks_by_title.json", [chunk.to_dict() for chunk in chunks]
        )
        return chunks
    except Exception as e:
        _logger.error(f"Error creating chunks by title: {e}")
        return None


def separate_content_types(chunk: Element):
    """
    Separates text, tables (HTML) and images (base64) from a chunk and returns them in a structured format.
    """

    try:
        _logger.info("Separating content types for chunk...")
        content_data: ContentData = {
            "text": chunk.text,
            "tables": [],
            "images": [],
            "types": ["text"],
        }

        if hasattr(chunk, "metadata") and hasattr(chunk.metadata, "orig_elements"):
            for element in chunk.metadata.orig_elements:
                element_type = type(element).__name__

                # Store tables as HTML and images as base64
                if element_type == "Table":
                    content_data["types"].append("table")

                    table_html = getattr(element.metadata, "text_as_html", element.text)
                    if table_html:
                        content_data["tables"].append(table_html)

                    if (
                        hasattr(element, "metadata")
                        and hasattr(element.metadata, "image_base64")
                        and element.metadata.image_base64
                    ):
                        content_data["types"].append("image")
                        content_data["images"].append(element.metadata.image_base64)

                elif element_type == "Image":
                    if (
                        hasattr(element, "metadata")
                        and hasattr(element.metadata, "image_base64")
                        and element.metadata.image_base64
                    ):
                        content_data["types"].append("image")
                        content_data["images"].append(element.metadata.image_base64)

        content_data["types"] = list(set(content_data["types"]))
        _logger.info("Content types found: %s", content_data["types"])
        return content_data
    except Exception as e:
        _logger.error("Error separating content types: %s", e)
        return None


async def process_single_chunk(i, len_chunks, chunk, file_metadata, semaphore):
    """Helper coroutine to process a single chunk under the semaphore limit."""
    chunk_id = getattr(chunk, "id", str(uuid.uuid4()))
    content_data = separate_content_types(chunk)

    if content_data is None:
        _logger.warning(
            "Failed to separate content types for chunk %d. Skipping.", i + 1
        )
        return None, None

    # Prepare metadata
    metadata = getattr(chunk, "metadata", None)
    pages = set([getattr(metadata, "page_number", "N/A")])
    orig_elements = getattr(metadata, "orig_elements", [])

    for element in orig_elements:
        pages.add(getattr(getattr(element, "metadata", None), "page_number", "N/A"))

    base_metadata = {"page": list(pages), **file_metadata}

    enhanced_summary_text = ""
    structured_data = {}

    if content_data["images"]:
        async with semaphore:
            _logger.info("Processing LLM summary for chunk %d/%d...", i + 1, len_chunks)
            enhanced_content_json = await enhancer.agenerate_summaries(
                content_data["text"], content_data["images"]
            )

        if enhanced_content_json:
            try:
                structured_data = json.loads(enhanced_content_json)
                summary = structured_data.get("comprehensive_summary", "")
                visual_analysis = structured_data.get("visual_analysis", "")

                if summary:
                    enhanced_summary_text += f"### Summary\n{summary}\n"
                if visual_analysis:
                    enhanced_summary_text += f"### Visual Analysis\n{visual_analysis}\n"

            except json.JSONDecodeError as e:
                _logger.error(
                    "Failed to decode enhanced content JSON for chunk %d: %s", i + 1, e
                )

    # Parent payload
    parent_payload = f"### Text Content\n{content_data['text']}\n\n"
    if enhanced_summary_text:
        parent_payload += f"{enhanced_summary_text}\n\n"

    parent_metadata = {
        "id": chunk_id,
        **base_metadata,
        "type_chunk": "parent",
        "tables_html": content_data["tables"],
        "images_base64": content_data["images"],
    }

    parent_doc = Document(page_content=parent_payload.strip(), metadata=parent_metadata)

    # Build Child Documents
    local_child_docs = []
    if structured_data and structured_data.get("comprehensive_summary", ""):
        summary_chunks = child_text_splitter.split_text(
            structured_data["comprehensive_summary"]
        )

        for summary_piece in summary_chunks:
            raw_metadata = {
                "parent_id": chunk_id,
                "id": str(uuid.uuid4()),
                "type_chunk": "child",
                "type": "summary",
                "answered_questions": structured_data.get("answered_questions", []),
                "search_keywords": structured_data.get("search_keywords", []),
                "visual_analysis": structured_data.get("visual_analysis", ""),
                **base_metadata,
            }
            clean_metadata = {
                k: v for k, v in raw_metadata.items() if v not in ([], "", None)
            }
            local_child_docs.append(
                Document(page_content=summary_piece, metadata=clean_metadata)
            )

    for element in orig_elements:
        element_type = type(element).__name__
        if (
            element_type not in ["Table", "Image"]
            and hasattr(element, "text")
            and element.text
        ):
            text_chunks = child_text_splitter.split_text(element.text)
            for safe_text in text_chunks:
                local_child_docs.append(
                    Document(
                        page_content=safe_text,
                        metadata={
                            "parent_id": chunk_id,
                            "id": str(uuid.uuid4()),
                            "type_chunk": "child",
                            "type": element_type.lower(),
                            **base_metadata,
                        },
                    )
                )

    return (chunk_id, parent_doc), local_child_docs


async def build_retrieval_chunks(chunks: list[Element], file_metadata: dict):
    """
    Creates parent-child documents concurrently with a concurrency limit.
    """
    try:
        _logger.info("Creating parent-child documents asynchronously...")

        max_concurrency = config.MAX_CONCURRENT_LLM_SUMMARY_REQUESTS
        semaphore = asyncio.Semaphore(max_concurrency)

        tasks = [
            process_single_chunk(i, len(chunks), chunk, file_metadata, semaphore)
            for i, chunk in enumerate(chunks)
        ]

        results = await asyncio.gather(*tasks)

        parent_docs = []
        child_docs = []

        for parent_res, children in results:
            if parent_res:
                parent_docs.append(parent_res)
            if children:
                child_docs.extend(children)

        _logger.info(
            "Created %d parents and %d children.", len(parent_docs), len(child_docs)
        )
        return parent_docs, child_docs

    except Exception as e:
        _logger.error("Error creating parent-child documents: %s", e)
        return [], []
