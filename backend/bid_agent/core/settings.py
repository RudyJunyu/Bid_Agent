"""Environment configuration and paths independent of the launch directory."""
import os
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / '.env', override=False)


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {'1', 'true', 'yes', 'on'}


def resolve_path(name: str, default: str) -> Path:
    path = Path(os.getenv(name) or default).expanduser()
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


STORAGE_DIR = resolve_path('BID_STORAGE_DIR', 'storage')
DB_PATH = resolve_path('BID_DB_PATH', str(STORAGE_DIR / 'data' / 'bid_agent.db'))
CHROMA_DIR = resolve_path('CHROMA_PERSIST_DIR', str(STORAGE_DIR / 'chroma'))
MAX_UPLOAD_BYTES = int(os.getenv('BID_MAX_UPLOAD_MB', '50')) * 1024 * 1024
CORS_ORIGINS = [v.strip() for v in os.getenv('BID_CORS_ORIGINS', '').split(',') if v.strip()]
ALLOW_SERVER_PATHS = env_bool('BID_ALLOW_SERVER_PATHS')
BUILD_VERSION = '0.2.0'
ROOT_PATH = os.getenv('BID_ROOT_PATH', '').rstrip('/')
