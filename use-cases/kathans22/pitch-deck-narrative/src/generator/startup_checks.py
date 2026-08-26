"""Startup config checks — name the cause and the fix, then refuse to boot."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from generator.manifest import project_root


class StartupConfigError(SystemExit):
    """Process exit with a cause+fix message already printed to stderr."""


def _emit(error: str, cause: str, fix: str) -> None:
    print(f"ERROR: {error}", file=sys.stderr)
    print(f"Cause: {cause}", file=sys.stderr)
    print(f"Fix: {fix}", file=sys.stderr)


def require_runtime_config(*, require_api_key: bool = True) -> None:
    """Validate config tree and SuperDocs key before serving or generating.

    Raises ``StartupConfigError`` (exits the process) when a required piece is missing.
    """
    root = project_root()
    config = root / "config"
    manifest = config / "deck-manifest.yaml"

    if not config.is_dir():
        _emit(
            "config/ directory is missing.",
            f"Expected {config} next to the installed package root.",
            "Run commands from use-cases/kathans22/pitch-deck-narrative after "
            "pip install -e ., or rebuild the Docker image from that folder.",
        )
        raise StartupConfigError(1)

    if not manifest.is_file():
        _emit(
            "config/deck-manifest.yaml is missing.",
            f"No deck manifest at {manifest}.",
            "Ensure config/deck-manifest.yaml is present, then restart "
            "(docker compose up --build, or uvicorn generator.api.app:app).",
        )
        raise StartupConfigError(1)

    if not require_api_key:
        return

    key = (os.environ.get("SUPERDOCS_API_KEY") or "").strip()
    if not key:
        env_path = root / ".env"
        _emit(
            "SUPERDOCS_API_KEY is not set.",
            "The process environment has no SuperDocs API key "
            f"(looked for SUPERDOCS_API_KEY; local file would be {env_path}).",
            "cp .env.example .env  then set SUPERDOCS_API_KEY=sk_… from "
            "use.superdocs.app → Settings → API Keys, then restart.",
        )
        raise StartupConfigError(1)

    if key == "your-key-here":
        _emit(
            "SUPERDOCS_API_KEY is still the placeholder.",
            ".env (or the environment) still has SUPERDOCS_API_KEY=your-key-here.",
            "Replace your-key-here with a real sk_ key, save .env, then restart.",
        )
        raise StartupConfigError(1)
