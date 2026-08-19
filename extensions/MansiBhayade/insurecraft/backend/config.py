import os
from dotenv import load_dotenv

load_dotenv()

SUPERDOCS_API_KEY = os.getenv("SUPERDOCS_API_KEY")
SUPERDOCS_BASE_URL = os.getenv(
    "SUPERDOCS_BASE_URL",
    "https://api.superdocs.app"
)

if not SUPERDOCS_API_KEY:
    raise RuntimeError(
        "SUPERDOCS_API_KEY is missing. "
        "Add it to the .env file."
    )