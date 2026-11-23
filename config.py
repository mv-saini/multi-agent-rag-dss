from dotenv import load_dotenv
import os

load_dotenv()

# Paths and Storage
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
MAX_UPLOAD_SIZE_BYTES = int(str(50 * 1024 * 1024))

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
IMAGE_STORE_DIR = os.path.join(DATA_DIR, "images")

INGESTION_MAX_CONCURRENT_DOCUMENTS = 3

# Lanzano 2019 scenarios
SEISMIC_INPUT_DIR = os.path.join(DATA_DIR, "qgis", "scenario")
SEISMIC_FAULT_PATH = os.path.join(
    SEISMIC_INPUT_DIR,
    "ISS_Individual Seismogenic Sources",
    "DISS331_iss331_POLIGONI_EPSG-32633.shp",
)
SEISMIC_VS30_PATH = os.path.join(SEISMIC_INPUT_DIR, "Vs_30", "vs_30.tif")
SEISMIC_COEFFICIENT_PATH = os.path.join(
    SEISMIC_INPUT_DIR, "Tabelle", "2018210_esupp_Table_S2.csv"
)
SEISMIC_CRS = "EPSG:32633"
SEISMIC_RESOLUTION_M = float(500)
SEISMIC_BUFFER_KM = float(100)
SEISMIC_MAX_CELLS = int(500000)
SEISMIC_GRID_ORIGIN_X = 0.0
SEISMIC_GRID_ORIGIN_Y = 0.0
SEISMIC_PGA_POINT_INTERVAL = float(0.005)
SEISMIC_PGA_RASTER_INTERVAL = float(0.00015)
SEISMIC_DEFAULT_IM = "PGA"
SEISMIC_DEFAULT_PERIOD_S = 0.2

POSTGRES_DSN = os.getenv("POSTGRES_DSN")
POSTGRES_POOL_MIN_SIZE = int(os.getenv("POSTGRES_POOL_MIN_SIZE", "2"))
POSTGRES_POOL_MAX_SIZE = int(os.getenv("POSTGRES_POOL_MAX_SIZE", "10"))
POSTGRES_POOL_TIMEOUT_SECONDS = float(os.getenv("POSTGRES_POOL_TIMEOUT_SECONDS", "10"))


def get_postgres_dsn() -> str:
    if not POSTGRES_DSN:
        raise RuntimeError("POSTGRES_DSN must be set before connecting to PostgreSQL.")
    return POSTGRES_DSN


# Auth
JWT_ALGORITHM = "HS256"
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-only")
REFRESH_COOKIE_NAME = "refresh_token"
REFRESH_TOKEN_EXPIRATION_SEC = 7 * 24 * 60 * 60
ACCESS_COOKIE_NAME = "access_token"
ACCESS_TOKEN_EXPIRATION_SEC = 60 * 60
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

# Models
OPENAI_EMBEDDING_MODEL = "text-embedding-3-large"
OPENAI_EMBEDDING_DIMENSIONS = 3072
CROSS_ENCODER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
CROSS_ENCODER_DEVICE = os.getenv(
    "CROSS_ENCODER_DEVICE", "cpu"
)  # "cuda" | "mps" | "cpu"
RERANK_BATCH_SIZE = 16
RERANK_STRATEGY = "one_to_one"  # "one_to_one" | "all_to_all"

OPEN_AI = True
# OPEN_AI_MODEL = "gpt-5.6-luna"
OPEN_AI_MODEL = "gpt-6-luna"

# RAG Settings
MAX_CHARACTERS = 4500
CHILD_CHUNK_SIZE = 1500
CHILD_CHUNK_OVERLAP = 150

# Retrieval Settings
RETRIEVAL_K = 20
FETCH_K = 40
MMR_LAMBDA = 0.6
HYBRID_SEARCH_ENABLED = True
SPARSE_RETRIEVAL_K = 20
RRF_ALPHA = 60
RERANK_TOP_K = 10
MIN_RELEVANCE_SCORE = None
MAX_RAG_IMAGES = 12

# Web Search Settings
WEB_MAX_SEARCHES = 5
WEB_MAX_EXTRACTIONS = 2
WEB_MAX_RESULTS_PER_SEARCH = 5
WEB_MAX_PASSAGE_READS = 12
WEB_PASSAGE_PREVIEW_CHARS = 400
WEB_PASSAGE_CHARS = 2_000
WEB_TOOL_TIMEOUT_SECONDS = 60

# Logging
CONSOLE_LOGGING = True
