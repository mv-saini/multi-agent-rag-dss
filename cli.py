import os
import sys
import argparse
from core.indexing.ingestion import IngestionError, ingest_document
from utils import logger
from dotenv import load_dotenv
from langfuse.langchain import CallbackHandler

load_dotenv()


def run_load(filepath: str):
    _logger = logger.setup_logger("load")
    if not os.path.exists(filepath):
        _logger.error("Error: File %s does not exist.", filepath)
        sys.exit(1)

    langfuse_handler = CallbackHandler()
    llm_config = {"callbacks": [langfuse_handler]} if langfuse_handler else {}

    _logger.info("Loading %s...", filepath)

    try:
        result = ingest_document(filepath, run_config=llm_config)
    except IngestionError as exc:
        _logger.error("Ingestion failed: %s", exc)
        sys.exit(1)

    _logger.info(
        "Done! Indexed %(filename)s (%(parent_chunks)d parent and %(child_chunks)d child chunks).",
        result,
    )


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
