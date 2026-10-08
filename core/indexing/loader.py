from unstructured.partition.pdf import partition_pdf
from unstructured.documents.elements import Element
import config
from utils import logger
from pypdf import PdfReader
from core.indexing import enhancer
import os
import logging

_logger = logging.getLogger(__name__)


def extract_metadata(filepath: str):
    """
    Extracts and cleans metadata from a PDF file.
    """

    try:
        _logger.info("Extracting metadata from PDF: %s...", filepath)

        reader = PdfReader(filepath)
        meta = reader.metadata

        # remove leading '/'
        clean_meta = {}
        if meta:
            for key, value in meta.items():
                clean_key = key.strip("/").lower()
                if clean_key in config.FILE_METADATA_AVOID:
                    continue
                clean_meta[f"doc_{clean_key}"] = str(value)
        return clean_meta
    except Exception as e:
        _logger.error(f"Failed to extract PDF metadata: {e}")
        return None


def partition_document(file_path: str):
    """
    Partitions a PDF document into individual elements using unstructured lib.
    """

    _logger.info("Partitioning PDF: %s...", file_path)

    try:
        elements = partition_pdf(
            filename=file_path,
            strategy="hi_res",
            infer_table_structure=True,
            hi_res_model_name="yolox",
            extract_image_block_types=["Image", "Table"],
            extract_image_block_to_payload=True,
        )

        _logger.info("Total elements extracted: %d", len(elements))
        logger.save_artifact(
            "partitioned_elements.json", [el.to_dict() for el in elements]
        )

        return elements
    except Exception as e:
        _logger.error(f"Error partitioning document: {e}")
        return None


def build_document_index(elements: list[Element]):
    """
    Creates a document index based on title elements for better retrieval and context.
    """

    try:
        doc_index = {}
        index = 1
        for element in elements:
            if element.category in ["Title"]:
                doc_index[index] = {
                    "title": element.text.strip(),
                    "page_number": getattr(element.metadata, "page_number", "N/A"),
                }
                index += 1
        _logger.info("Document index created with %d titles.", len(doc_index))
        logger.save_artifact("doc_index.json", doc_index)
        return doc_index
    except Exception as e:
        _logger.error(f"Error creating document index: {e}")
        return None


def load_document(filepath: str):
    try:
        elements = partition_document(filepath)

        if elements is None:
            raise Exception("Failed to partition document.")

        file_metadata = extract_metadata(filepath)
        doc_index = build_document_index(elements)

        if doc_index is not None and file_metadata is not None:
            if (
                file_metadata.get("doc_title", None) is None
                or file_metadata["doc_title"] == "N/A"
                or file_metadata["doc_title"].strip() == ""
            ):
                inferred_title = enhancer.get_inferred_doc_title(doc_index)
                file_metadata["doc_title"] = inferred_title
                _logger.info(f"Inferred document title: {inferred_title}")
        else:
            _logger.warning(
                "Could not create doc index or extract file metadata. Skipping title inference."
            )

            if file_metadata is None:
                file_metadata = {}

            if doc_index is None:
                doc_index = {}

        source = os.path.basename(filepath)
        file_metadata["source"] = source

        return elements, file_metadata, doc_index
    except Exception as e:
        _logger.error(f"Error during ingestion: {e}")
        return None, None, None
