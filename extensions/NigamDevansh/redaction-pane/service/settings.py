"""One typed boundary for configuration, and where the defaults are stated.

Its own file, not the analyst's: this app is a `cp -r` into another repo and
cannot inherit a configuration system it does not carry. Absence degrades, never
crashes — a pane with no SuperDocs key still scans and redacts in place through
Word; it just cannot export a clean file, and says so.

See extensions/redaction-pane/README.md § "Configuration".
"""

from __future__ import annotations

from functools import lru_cache
from importlib.util import find_spec
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "gemini": "gemini-3.6-flash",
    "anthropic": "claude-sonnet-5",
}
"""What tier 3 runs when `LLM_MODEL_PII` is blank. Pinned here, not left to the
SDK's moving default, so the same document redacts the same way between runs."""

PROVIDER_SDK = {"openai": "openai", "gemini": "google.genai", "anthropic": "anthropic"}
"""Import name of each provider's client. The image bakes ONE provider (the
`LLM_PROVIDER` build arg), openai by default, so `/health` can say a tier-3 call
would fail for want of the SDK instead of finding out at the first scan."""


def _sdk_present(module: str) -> bool:
    """Whether an import would succeed, tolerating a missing namespace parent
    (`find_spec('google.genai')` raises rather than returns None when `google`
    itself is absent)."""
    try:
        return find_spec(module) is not None
    except ModuleNotFoundError:
        return False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    # ── credentials ───────────────────────────────────────────────────────
    superdocs_api_key: str = ""
    llm_provider: Literal["openai", "gemini", "anthropic"] = "openai"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    anthropic_api_key: str = ""
    llm_model_pii: str = ""
    """Blank → `DEFAULT_MODELS[llm_provider]`. Tier 3 only. Set it to run
    something cheaper or newer without touching anything else."""

    superdocs_base_url: str = "https://api.superdocs.app"
    sd_timeout_s: float = 120.0

    # No host/port/certificate settings. HTTPS is required (Office refuses an
    # http:// SourceLocation), but uvicorn gets the key/cert on its command line
    # in the Dockerfile — fields here would be read by nothing.

    # ── storage ───────────────────────────────────────────────────────────
    data_dir: Path = ROOT / "data"
    """Everything this app writes, in three folders:

        data/db/       the SQLite log — ours, not something to open
        data/logs/     exported logs, one CSV per click
        data/exports/  clean copies of documents

    Kept apart from the exports a reviewer wants, so "what is this / did I make
    it" does not come up."""

    # ── detection ─────────────────────────────────────────────────────────
    gliner_enabled: bool = True
    """Tier 2, on by default — the model and torch are baked into the image, so
    it costs image size at build and nothing at run. It finds a name in prose
    locally, without a network call. Set `false` to skip it; `settings.tiers`
    then says so, so a scan with it off is never mistaken for a clean document."""
    gliner_model: str = "knowledgator/gliner-pii-base-v1.0"
    gliner_threshold: float = 0.5
    llm_enabled: bool = True

    # ── behaviour ─────────────────────────────────────────────────────────
    verify_export: bool = True

    @property
    def llm_api_key(self) -> str:
        return {
            "openai": self.openai_api_key,
            "gemini": self.gemini_api_key,
            "anthropic": self.anthropic_api_key,
        }[self.llm_provider]

    @property
    def llm_model(self) -> str:
        return self.llm_model_pii.strip() or DEFAULT_MODELS[self.llm_provider]

    @property
    def database_path(self) -> Path:
        return self.data_dir / "db" / "redaction.db"

    def missing_requirements(self) -> list[str]:
        """Everything absent at once, each with the capability it costs. Reported
        on `/health` and in the pane, so "why can I not export" is on screen."""
        missing: list[str] = []
        if not self.superdocs_api_key:
            missing.append(
                "SUPERDOCS_API_KEY — export of a cleaned file is disabled. "
                "Scanning and in-place redaction still work."
            )
        if self.gliner_enabled and find_spec("gliner") is None:
            missing.append(
                "gliner is not installed — tier 2 is disabled. The Docker image "
                "carries it; a local run needs: pip install '.[ner]'"
            )
        if self.llm_enabled and not _sdk_present(PROVIDER_SDK[self.llm_provider]):
            missing.append(
                f"the {self.llm_provider} SDK is not installed in this image — tier 3 "
                "is disabled. openai is the default and always present; to use "
                f"{self.llm_provider}, set LLM_PROVIDER={self.llm_provider} and rebuild "
                "(make up). Pattern detection still runs."
            )
        elif self.llm_enabled and not self.llm_api_key:
            var = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY",
                   "anthropic": "ANTHROPIC_API_KEY"}[self.llm_provider]
            missing.append(
                f"{var} — tier 3 is disabled: names in prose, addresses and "
                "privileged passages will not be found. Pattern detection still runs."
            )
        return missing

    @property
    def tiers(self) -> list[str]:
        """Which detectors this configuration can actually run.

        `gliner_enabled` is a setting; the installed package is a fact, checked
        with `find_spec`. Listing `ner` while the import fails would report a
        document clean on a detector that never ran."""
        active = ["patterns"]
        if self.gliner_enabled and find_spec("gliner") is not None:
            active.append("ner")
        if self.llm_enabled and self.llm_api_key and _sdk_present(PROVIDER_SDK[self.llm_provider]):
            active.append("llm")
        return active


@lru_cache
def get_settings() -> Settings:
    return Settings()
