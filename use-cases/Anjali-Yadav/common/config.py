"""
Shared configuration for the SuperDocs Task 2 use cases.

Configuration precedence:
    1. Existing process environment variables
    2. .env file discovered from the application/project directory

Environment variables intentionally win over .env values so CI/CD,
Docker, and production deployments can inject secrets without modifying
source-controlled files.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_environment(app_dir: Path | None = None) -> None:
    """
    Load environment variables from a .env file.

    Existing environment variables are never overwritten.

    Args:
        app_dir:
            Directory containing the application's .env file.
            If omitted, the current working directory is used.
    """
    directory = app_dir or Path.cwd()
    env_file = directory / ".env"

    if env_file.is_file():
        load_dotenv(env_file, override=False)


def get_required_api_key() -> str:
    """
    Return the configured SuperDocs API key.

    Raises:
        RuntimeError: if no API key is configured.
    """
    api_key = os.environ.get("SUPERDOCS_API_KEY", "").strip()

    if not api_key:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is not configured. "
            "Set it in the environment or in the application's .env file."
        )

    return api_key


def get_budget_floor(default: int = 20) -> int:
    """Return the configured SuperDocs operation budget floor."""
    raw_value = os.environ.get(
        "SUPERDOCS_BUDGET_FLOOR",
        str(default),
    )

    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(
            "SUPERDOCS_BUDGET_FLOOR must be an integer."
        ) from exc

    if value < 0:
        raise RuntimeError(
            "SUPERDOCS_BUDGET_FLOOR cannot be negative."
        )

    return value