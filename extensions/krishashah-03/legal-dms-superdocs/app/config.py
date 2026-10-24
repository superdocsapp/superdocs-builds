"""
Configuration loaded from environment variables. Nothing secret is ever
hard-coded here or logged - see SuperDocsClient for the one place the API
key is read into a header.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    superdocs_api_key: str | None = os.getenv("SUPERDOCS_API_KEY")
    superdocs_base_url: str = os.getenv("SUPERDOCS_BASE_URL", "https://api.superdocs.app")


settings = Settings()
