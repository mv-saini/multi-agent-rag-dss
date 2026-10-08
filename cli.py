import os
import sys
import argparse
import asyncio
from core.indexing import loader, processor
from core.storage import sql_database, vector_store
from utils import logger
from dotenv import load_dotenv
from langfuse import get_client
from langfuse.langchain import CallbackHandler
import config

load_dotenv()


def run_load(filepath: str):
    _logger = logger.setup_logger("load")
    if not os.path.exists(filepath):
        _logger.error("Error: File %s does not exist.", filepath)
        sys.exit(1)

    langfuse_handler = CallbackHandler()
    llm_config = {"callbacks": [langfuse_handler]} if langfuse_handler else {}
    config.llm_config = llm_config

    _logger.info("Loading %s...", filepath)

    elements, file_metadata, doc_index = loader.load_document(filepath)

    chunks_by_title = processor.create_chunks_by_title(elements)

    if chunks_by_title is None or file_metadata is None or doc_index is None:
        _logger.error("Ingestion failed. Aborting load process.")
        sys.exit(1)

    _logger.info("Total initial chunks created: %d", len(chunks_by_title))

    parent_docs, child_docs = asyncio.run(
        processor.build_retrieval_chunks(chunks_by_title, file_metadata)
    )

    if not parent_docs or not child_docs:
        _logger.error("Failed to create parent-child documents. Aborting load process.")
        sys.exit(1)

    logger.save_docs_artifact("parent_chunks.json", parent_docs)
    logger.save_docs_artifact("child_chunks.json", child_docs)

    vector_store.store_documents(parent_docs, child_docs)

    sql_database.initialize_schema()
    sql_database.store_document_metadata(file_metadata, doc_index)

    get_client().flush()

    _logger.info("Done! Ready for retrieval.")


def main():
    parser = argparse.ArgumentParser(description="RAG CLI Tool")
    subparsers = parser.add_subparsers(dest="command")

    # Ingest command
    ingest_parser = subparsers.add_parser(
        "load", help="Load and process a PDF document"
    )
    ingest_parser.add_argument("filepath", type=str, help="Path to the PDF file")

    args = parser.parse_args()

    if args.command == "load":
        run_load(args.filepath)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
