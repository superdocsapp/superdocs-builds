from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # No trailing /v1 — the client builds full paths itself, matching
    # docs.superdocs.app exactly (e.g. /v1/documents/upload).
    superdocs_base_url: str = "https://api.superdocs.app"
    superdocs_api_key: str = ""
    export_format: str = "pdf"
    superdocs_model_tier: str | None = None
    # Substitution correctness is the entire point of this build, and
    # the documents are a few KB each — the cost difference between
    # "balanced" and "deep" reasoning is negligible here, while "deep"
    # gives the model more room to get every one of 7 substitutions
    # right on the first pass (see docs.superdocs.app/guides/model
    # -selection: "AI edited sections you didn't ask about... verify
    # your prompt is single-section explicit" and "deep... gives it
    # room to reason carefully about wording"). Overridable via env.
    superdocs_thinking_depth: str | None = "deep"

    # "ask_every_time" (default) exercises the documented four-endpoint
    # contract (upload, chat/async, approve, export) with every change
    # auto-approved by the batch runner — no human reviewer needed for
    # this card, but the real approval mechanism is genuinely exercised
    # rather than skipped. "approve_all" is the faster single-call
    # alternative. See README "Why ask_every_time, not approve_all".
    superdocs_approval_mode: str = "ask_every_time"

    superdocs_poll_interval_seconds: float = 2.0
    superdocs_max_wait_seconds: float = 300.0
    superdocs_max_retries: int = 5
    superdocs_retry_base_delay_seconds: float = 1.0
    superdocs_request_timeout_seconds: float = 60.0

    # "Budget your operations" (task brief) — a small-sample mode and a
    # stopping rule. None = process every lead in the CSV.
    max_leads_per_run: int | None = None

    @field_validator(
        "max_leads_per_run", "superdocs_model_tier", "superdocs_thinking_depth", mode="before"
    )
    @classmethod
    def _blank_env_value_means_unset(cls, value):
        # pydantic-settings raises a validation error at startup if an
        # Optional[int]/Optional[str] field is set to an empty string in
        # .env, which .env.example intentionally does for several
        # optional fields — an empty value should mean "unset", not
        # "crash before the pipeline even starts."
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


def get_settings() -> Settings:
    return Settings()
