import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

API_BASE = os.getenv("SUPERDOCS_API_BASE", "https://api.superdocs.app")
API_KEY = os.getenv("SUPERDOCS_API_KEY", "")
MODEL_TIER = os.getenv("SUPERDOCS_MODEL_TIER", "pro")
THINKING_DEPTH = os.getenv("SUPERDOCS_THINKING_DEPTH", "balanced")

JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "gemini")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

DATA_DIR = BASE_DIR / "data"
CORPUS_DIR = DATA_DIR / "corpus"
EDITS_DIR = DATA_DIR / "edits"
JUDGMENTS_DIR = DATA_DIR / "judgments"
HUMAN_DIR = JUDGMENTS_DIR / "human"
AUTO_DIR = JUDGMENTS_DIR / "auto"
REPORT_DIR = BASE_DIR / "report"
LEDGER_PATH = DATA_DIR / "ledger.jsonl"
GEMINI_LEDGER_PATH = DATA_DIR / "ledger_gemini.jsonl"
RUBRIC_PATH = DATA_DIR / "rubric.json"
INSTRUCTIONS_PATH = DATA_DIR / "instructions.json"

SMALL_SAMPLE_CASES = 6
FULL_SAMPLE_CASES = 11

DEFAULT_BUDGET_CAP_OPS = 60

for d in (EDITS_DIR, HUMAN_DIR, AUTO_DIR, REPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)


def require_key() -> str:
    if not API_KEY:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is not set. Copy data/.env.example to .env and fill it in."
        )
    return API_KEY