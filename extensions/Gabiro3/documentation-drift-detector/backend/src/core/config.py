import os
from pathlib import Path

# backend/src/core/config.py -> backend/
BACKEND_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = Path(__file__).resolve().parents[1]


def _load_env_files() -> None:
    """Load .env into os.environ before any config value is read.

    Looked up in order; later files do NOT override values already set
    (real environment variables always win):
      1. backend/.env          <- where the keys actually live
      2. backend/config/.env   <- documented alternate location
    """
    candidates = [BACKEND_ROOT / ".env", BACKEND_ROOT / "config" / ".env"]
    try:
        from dotenv import load_dotenv

        for path in candidates:
            if path.is_file():
                load_dotenv(path, override=False)
        return
    except ImportError:
        pass

    # Minimal fallback parser so config still works without python-dotenv.
    for path in candidates:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip().strip('"').strip("'")
            os.environ.setdefault(key, value)


_load_env_files()

DATABASE_URL: str = os.getenv(
    "DRIFT_DB_URL",
    "postgresql+asyncpg://drift_detector:drift_detector@localhost:5432/drift_detector",
)

# --- SuperDocs (https://api.superdocs.app) ---
SUPERDOCS_API_BASE: str = os.getenv("SUPERDOCS_API_BASE", "https://api.superdocs.app")
SUPERDOCS_API_KEY: str = os.getenv("SUPERDOCS_API_KEY", "")
SUPERDOCS_SESSION_ID: str = os.getenv("DRIFT_SUPERDOCS_SESSION", "drift-detector-main")
# One wrong word matters when applying an edit, so default to the strongest tier.
SUPERDOCS_MODEL_TIER: str = os.getenv("DRIFT_SUPERDOCS_MODEL", "max")

# --- LLM providers ---
ANTHROPIC_ENDPOINT: str = os.getenv("ANTHROPIC_ENDPOINT", "")
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_DEPLOYMENT: str = os.getenv("ANTHROPIC_DEPLOYMENT", "")

AZURE_OPENAI_ENDPOINT: str = os.getenv("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_KEY: str = os.getenv("AZURE_OPENAI_KEY", "")
AZURE_OPENAI_DEPLOYMENT: str = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
AZURE_EMBEDDING_DEPLOYMENT: str = os.getenv(
    "AZURE_EMBEDDING_DEPLOYMENT", "text-embedding-3-small"
)

# Must match the pgvector column width in migrations/001_init.sql
# (chunks.embedding vector(1536)). text-embedding-3-small and ada-002 are
# 1536; text-embedding-3-large is 3072 and needs the column widened.
EMBEDDING_DIM: int = int(os.getenv("DRIFT_EMBEDDING_DIM", "1536"))

BUDGET_MAX_OPS: int = int(os.getenv("DRIFT_BUDGET_MAX_OPS", "200"))
BUDGET_MAX_TOKENS: int = int(os.getenv("DRIFT_BUDGET_MAX_TOKENS", "100000"))
RETRIEVER_TOP_K: int = int(os.getenv("DRIFT_RETRIEVER_TOP_K", "10"))
FAILED_RETRY_CAP: int = int(os.getenv("DRIFT_FAILED_RETRY_CAP", "3"))
FAILED_RETRY_BACKOFF_BASE: float = float(
    os.getenv("DRIFT_FAILED_RETRY_BACKOFF_BASE", "2.0")
)

WATCHED_DIR: Path = Path(
    os.getenv("DRIFT_WATCHED_DIR", str(BACKEND_ROOT / "watched"))
)
