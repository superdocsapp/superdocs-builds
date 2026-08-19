from __future__ import annotations

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # S3 / MinIO — boto3 reads standard AWS_* env vars for credentials.
    # These are the only bucket-shape config the pipeline needs.
    s3_bucket: str = "vendor-docs"
    s3_incoming_prefix: str = "incoming/"
    s3_processed_prefix: str = "processed/"
    s3_failed_prefix: str = "failed/"
    s3_endpoint_url: str | None = None  # set for MinIO/LocalStack; None for real AWS
    s3_region: str = "us-east-1"
    presigned_url_ttl_seconds: int = 900

    # SuperDocs — no trailing /v1; the client builds full paths itself
    # (e.g. /v1/documents/upload) to match docs.superdocs.app exactly.
    superdocs_base_url: str = "https://api.superdocs.app"
    superdocs_api_key: str = ""
    superdocs_edit_instruction: str = (
        "Reformat this document to a clean, consistently styled version "
        "with corrected heading hierarchy. Preserve every fact and figure "
        "exactly as written; only change formatting and structure."
    )
    superdocs_export_format: str = "pdf"
    superdocs_model_tier: str | None = None  # e.g. "core", "pro", "max" — None = API default
    superdocs_thinking_depth: str | None = None  # e.g. "fast", "balanced", "deep"

    # approve_all: one synchronous POST /v1/chat call, fewer round trips.
    # ask_every_time: the literal four-endpoint contract from the task
    # brief (upload, chat/async, approve, export), with every change
    # auto-approved by the pipeline rather than a human — see README
    # "Why ask_every_time + auto-approve, not approve_all" for the
    # reasoning. Either is a legitimate, fully-documented SuperDocs mode.
    superdocs_approval_mode: str = "ask_every_time"

    # Direct multipart upload to /v1/documents/upload is only reliable up
    # to ~20 MB per docs.superdocs.app/concepts/attachments ("Direct
    # inline and multipart uploads are reliable up to about 20 MB").
    # Anything at or above this threshold goes through the pre-signed
    # /v1/uploads -> PUT -> /v1/uploads/{id}/process flow instead (up to
    # 100 MB documented). Kept a few MB under 20 MB for safety margin.
    superdocs_direct_upload_max_bytes: int = 15_000_000
    # Pre-signed uploads take a "purpose" field. The docs give a worked
    # example only for purpose="export-html" (re-uploading HTML before
    # exporting a large document); no example purpose value is given for
    # ingesting a brand-new source document this way. This is a logged
    # assumption, not a guess baked in silently: override via env var if
    # the live API expects something else — it's the one place that
    # would need to change.
    superdocs_upload_purpose: str = "document-upload"

    # HITL polling — GET /v1/jobs/{job_id} until status settles.
    # docs.superdocs.app/guides/async-jobs gives typical latencies of
    # 30-180s for multi-section edits; 600s/2s gives generous headroom
    # without polling too aggressively.
    superdocs_poll_interval_seconds: float = 2.0
    superdocs_max_wait_seconds: float = 600.0

    # Retry behaviour for 429 (honour Retry-After) and 5xx (exponential
    # backoff), per docs.superdocs.app/errors/rate-limits.
    superdocs_max_retries: int = 5
    superdocs_retry_base_delay_seconds: float = 1.0
    superdocs_request_timeout_seconds: float = 120.0

    # Streaming — the whole point of this build. Chunk size bounds how
    # much of the file is ever resident in the orchestrator's memory at
    # once, regardless of total file size.
    stream_chunk_size_bytes: int = 262_144  # 256 KiB

    poll_interval_seconds: float = 5.0

    # "Budget your operations" (task brief, Task 2 notes) — a
    # small-sample mode + stopping rule. None = unbounded (production
    # behaviour); set to a small int while testing against a live key.
    max_files_per_run: int | None = None

    # .env.example ships several Optional[...] fields commented/blank so
    # a copy-paste .env with an empty value ("SUPERDOCS_MODEL_TIER=")
    # doesn't crash pydantic-settings on startup with an int/str parsing
    # error — an empty string is treated the same as the field being
    # unset. Found this the hard way while validating this build against
    # a real .env; worth guarding against for anyone else who copies
    # .env.example and leaves an optional line blank.
    @field_validator(
        "max_files_per_run",
        "superdocs_model_tier",
        "superdocs_thinking_depth",
        "s3_endpoint_url",
        mode="before",
    )
    @classmethod
    def _blank_env_value_means_unset(cls, value):
        if isinstance(value, str) and value.strip() == "":
            return None
        return value


def get_settings() -> Settings:
    return Settings()
