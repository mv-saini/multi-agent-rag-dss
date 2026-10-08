from langchain_core.runnables import RunnableConfig
import os

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")

CITY_ADMIN_BOUNDARY_PATH = os.path.join(
    DATA_DIR, "qgis/Limiti01012026/Com01012026/Com01012026_WGS84.shp"
)
PROVINCE_ADMIN_BOUNDARY_PATH = os.path.join(
    DATA_DIR, "qgis/Limiti01012026/ProvCM01012026/ProvCM01012026_WGS84.shp"
)
REGION_ADMIN_BOUNDARY_PATH = os.path.join(
    DATA_DIR, "qgis/Limiti01012026/Reg01012026/Reg01012026_WGS84.shp"
)
POP_GEOJSON_PATH = os.path.join(DATA_DIR, "qgis/popolazione/popolazione.shp")

# Paths and Storage
MAX_CONCURRENT_LLM_SUMMARY_REQUESTS = 1
CHROMA_DB_DIR = "data/chroma_db/vector_BGE_M3"
DOCSTORE_DIR = "data/docstore/vector_BGE_M3"
SQLITE_DB_PATH = "data/sqlite.db"
CHECKPOINT_DB = f"{DATA_DIR}/conversation_history/checkpoints.sqlite"
os.makedirs(os.path.dirname(CHECKPOINT_DB), exist_ok=True)

# Models
EMBEDDING_MODEL = "BAAI/bge-m3"
CROSS_ENCODER_MODEL = "BAAI/bge-reranker-v2-m3"
CROSS_ENCODER_DEVICE = os.getenv("CROSS_ENCODER_DEVICE", "mps")
RERANK_STRATEGY = "one_to_one"  # "one_to_one" | "all_to_all"

OPEN_AI = True
OPEN_AI_MODEL = "gpt-5.6-luna"

# RAG Settings
MAX_CHARACTERS = 3000
NEW_AFTER_N_CHARS = 2400
COMBINE_TEXT_UNDER_N_CHARS = 500

# Retrieval Settings
RETRIEVAL_K = 20
FETCH_K = 40
MMR_LAMBDA = 0.6
RRF_ALPHA = 60
RERANK_TOP_K = 10
MIN_RELEVANCE_SCORE = 0.6

# Web Search Settings

MAX_AGENT_STEPS = 5
MAX_SEARCH_CALLS = 3
MAX_EXTRACT_CALLS = 2
MAX_SEARCH_RESULTS = 5
MAX_EXTRACT_URLS = 3
MAX_CONTENT_CHARS = 12_000
RESULT_PREVIEW_CHARS = 1000
MAX_RESULTS_VISIBLE_TO_AGENT = 20

# Logging
CONSOLE_LOGGING = True

# Other
FILE_METADATA_AVOID = [
    "ptex.fullbanner",
    "creationdate",
    "moddate",
    "creator",
    "producer",
    "trapped",
]

llm_config: RunnableConfig | None = None
