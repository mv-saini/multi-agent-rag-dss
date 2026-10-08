import json
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_classic.retrievers import MultiVectorRetriever
from langchain_classic.storage import LocalFileStore, EncoderBackedStore
from langchain_core.documents import Document
import config
import logging

_logger = logging.getLogger(__name__)


def _doc_to_bytes(doc: Document) -> bytes:
    return json.dumps(doc.model_dump()).encode("utf-8")


def _bytes_to_doc(b: bytes) -> Document:
    return Document(**json.loads(b.decode("utf-8")))


def _init_vector_db():
    """
    Initializes the Chroma vector database collection with HuggingFace embeddings.
    """

    try:
        _logger.info("Initializing vector database collection: %s using embedding model: %s...",
                     config.CHROMA_DB_DIR, config.EMBEDDING_MODEL)

        model = HuggingFaceEmbeddings(
            model_name=config.EMBEDDING_MODEL
        )
        db = Chroma(
            persist_directory=config.CHROMA_DB_DIR,
            embedding_function=model,
            collection_metadata={"hnsw:space": "cosine"}
        )
        _logger.info("Initialized vector database collection.")
        return db
    except Exception as e:
        _logger.error("Error initializing vector database: %s", str(e))
        raise e


def get_doc_store():
    """
    Initializes a local file store to save the parent documents.
    """

    try:
        _logger.info("Initializing local document store at: %s",
                     config.DOCSTORE_DIR)

        file_store = LocalFileStore(config.DOCSTORE_DIR)

        # Automatically convert Documents to/from bytes
        store = EncoderBackedStore(
            store=file_store,
            key_encoder=lambda x: x,
            value_serializer=_doc_to_bytes,
            value_deserializer=_bytes_to_doc
        )
        return store
    except Exception as e:
        _logger.error("Error initializing document store: %s", str(e))
        raise e


def store_documents(parent_docs, child_docs, batch_size=100):
    """
    Stores parents in the docstore and children in the vector database in batches.
    """

    _logger.info("Storing %d children in Vector DB and %d parents in DocStore...",
                 len(child_docs), len(parent_docs))
    try:
        # Add Children to Vector Store in batches
        db = _init_vector_db()
        total_child_batches = (len(child_docs) + batch_size - 1) // batch_size

        for i in range(0, len(child_docs), batch_size):
            batch = child_docs[i:i + batch_size]
            current_batch_num = (i // batch_size) + 1
            _logger.info("Adding child batch %d/%d (size: %d)...",
                         current_batch_num, total_child_batches, len(batch))
            db.add_documents(batch)

        # Add Parents to Document Store in batches
        docstore = get_doc_store()
        total_parent_batches = (
            len(parent_docs) + batch_size - 1) // batch_size

        for i in range(0, len(parent_docs), batch_size):
            batch = parent_docs[i:i + batch_size]
            current_batch_num = (i // batch_size) + 1
            _logger.info("Adding parent batch %d/%d (size: %d)...",
                         current_batch_num, total_parent_batches, len(batch))
            docstore.mset(batch)

        _logger.info("Successfully stored all documents.")
    except Exception as e:
        _logger.error("Error storing chunks in databases: %s", str(e))


def get_retriever(file_filters: list[str] = None):
    """
    Initializes a MultiVectorRetriever with optional metadata filtering.
    """

    try:
        _logger.info("Creating MultiVectorRetriever...")

        vectorstore = _init_vector_db()
        docstore = get_doc_store()

        search_kwargs = {
            "k": config.RETRIEVAL_K,
            "lambda": config.MMR_LAMBDA,
            "fetch_k": config.FETCH_K
        }

        if file_filters:
            _logger.info(f"Applying metadata filter for files: {file_filters}")
            if len(file_filters) == 1:
                search_kwargs["filter"] = {"source": file_filters[0]}
            else:
                search_kwargs["filter"] = {"source": {"$in": file_filters}}

        return MultiVectorRetriever(
            vectorstore=vectorstore,
            docstore=docstore,
            id_key="parent_id",
            search_type="mmr",
            search_kwargs=search_kwargs
        )
    except Exception as e:
        _logger.error("Error creating retriever: %s", str(e))
        raise e
