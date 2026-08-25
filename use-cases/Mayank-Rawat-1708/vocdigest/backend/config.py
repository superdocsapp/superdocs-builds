"""
@file: backend/config.py
@description: Central configuration loaded from environment variables. Every tunable
    (API keys, database URL, model names, timeouts, retry budgets) resolves here so no
    other module reads os.environ directly. Secrets are never logged — the __repr__ is
    overridden to redact anything key-shaped.
@flow: Process start -> Settings() instantiated once as `settings` -> imported by
    services, nodes, and API routes -> validated lazily via require_* helpers so tests
    can run with no live keys at all.
@dependencies:
    - pydantic_settings.BaseSettings: env parsing + type coercion with .env support
    - functools.lru_cache: single settings instance per process
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MissingCredentialError(RuntimeError):
    """Raised when an operation needs a live API key that was never configured.

    Carries the env var name so the caller can surface an actionable message instead of
    a generic 401 from the upstream provider.
    """

    def __init__(self, env_var: str, purpose: str) -> None:
        self.env_var = env_var
        super().__init__(
            f"{env_var} is not set, so {purpose} cannot run. "
            f"Add it to .env (see .env.example). Tests run without it."
        )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- SuperDocs -------------------------------------------------------
    # Base URL has no trailing slash; every client path starts with "/v1/...".
    superdocs_api_key: str | None = Field(default=None, alias="SUPERDOCS_API_KEY")
    superdocs_base_url: str = Field(
        default="https://api.superdocs.app", alias="SUPERDOCS_BASE_URL"
    )
    # The docs cap a chat turn at 30 minutes wall clock. We poll well past our own
    # expected duration but below that ceiling, and treat a timeout as "still running,
    # surface it" rather than "crashed".
    superdocs_poll_timeout_s: int = Field(default=900, alias="SUPERDOCS_POLL_TIMEOUT_S")
    superdocs_poll_initial_s: float = Field(default=2.0, alias="SUPERDOCS_POLL_INITIAL_S")
    superdocs_poll_max_s: float = Field(default=15.0, alias="SUPERDOCS_POLL_MAX_S")
    superdocs_connect_timeout_s: float = Field(
        default=30.0, alias="SUPERDOCS_CONNECT_TIMEOUT_S"
    )
    # Which model tier SuperDocs should use for digest edits. The docs recommend pro/max
    # for high-stakes documents; a VoC digest that goes to execs qualifies.
    superdocs_model_tier: Literal["core", "turbo", "pro", "max"] = Field(
        default="pro", alias="SUPERDOCS_MODEL_TIER"
    )
    superdocs_thinking_depth: Literal["fast", "balanced", "deep"] = Field(
        default="balanced", alias="SUPERDOCS_THINKING_DEPTH"
    )

    # ---- Groq ------------------------------------------------------------
    groq_api_key: str | None = Field(default=None, alias="GROQ_API_KEY")
    groq_base_url: str = Field(
        default="https://api.groq.com/openai/v1", alias="GROQ_BASE_URL"
    )
    groq_model: str = Field(default="llama-3.3-70b-versatile", alias="GROQ_MODEL")
    # temperature=0 everywhere: idempotency requirement. Same input -> same output.
    groq_temperature: float = Field(default=0.0, alias="GROQ_TEMPERATURE")
    groq_timeout_s: float = Field(default=120.0, alias="GROQ_TIMEOUT_S")

    # ---- Groq token ceiling ----------------------------------------------
    # Groq counts a request's *requested* max_tokens against the per-minute allowance
    # before generating anything, so prompt + max_tokens must fit under the ceiling or
    # the call is rejected with a 413 having produced nothing.
    #
    # The real ceiling is read from the x-ratelimit-limit-tokens response header and
    # from the 413 body, both of which state it exactly. This setting is only the
    # bootstrap for the first request of a process, before any response has been seen;
    # it is overwritten by the observed value as soon as one arrives. Raise it if your
    # tier is larger — a too-low bootstrap only costs one extra split on the first call.
    groq_tpm_limit: int = Field(default=8000, alias="GROQ_TPM_LIMIT")
    # Held back from the ceiling on every request. Absorbs prompt-estimation error and
    # the fact that concurrent calls share one allowance.
    groq_tpm_headroom: int = Field(default=600, alias="GROQ_TPM_HEADROOM")
    # Smallest completion budget worth sending at all. Below this a reasoning model
    # spends the whole budget thinking and returns an empty completion, which the API
    # reports as a JSON validation failure for output that never existed.
    groq_min_completion_tokens: int = Field(
        default=384, alias="GROQ_MIN_COMPLETION_TOKENS"
    )
    # Extra completion budget added for reasoning models (gpt-oss and friends), which
    # emit reasoning tokens from the same budget as the answer. reasoning_effort="low"
    # keeps this small, but it is never zero.
    groq_reasoning_reserve_tokens: int = Field(
        default=512, alias="GROQ_REASONING_RESERVE_TOKENS"
    )
    # Published Groq free-tier pricing for llama-3.3-70b-versatile, USD per 1M tokens.
    # Used only for the cost report; wrong numbers here mis-report cost, nothing else.
    groq_input_cost_per_mtok: float = Field(
        default=0.59, alias="GROQ_INPUT_COST_PER_MTOK"
    )
    groq_output_cost_per_mtok: float = Field(
        default=0.79, alias="GROQ_OUTPUT_COST_PER_MTOK"
    )

    # ---- Database --------------------------------------------------------
    database_url: str = Field(
        default="postgresql+asyncpg://vocdigest:vocdigest@localhost:5432/vocdigest",
        alias="DATABASE_URL",
    )
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # Embedding width. Default matches all-MiniLM-L6-v2 (384). The pgvector column is
    # created from this value, so changing it after migrating requires a new migration.
    embedding_dim: int = Field(default=384, alias="EMBEDDING_DIM")
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2", alias="EMBEDDING_MODEL"
    )
    # "local" downloads a small sentence-transformers model. "hash" is a deterministic
    # offline stand-in used by tests so CI never pulls model weights.
    embedding_backend: Literal["local", "hash"] = Field(
        default="local", alias="EMBEDDING_BACKEND"
    )

    # ---- Run behaviour ---------------------------------------------------
    node_max_retries: int = Field(default=3, alias="NODE_MAX_RETRIES")
    node_retry_base_delay_s: float = Field(default=1.0, alias="NODE_RETRY_BASE_DELAY_S")
    max_conversation_chars: int = Field(
        default=8000, alias="MAX_CONVERSATION_CHARS"
    )
    # Conversations per LLM batch during classify/extract. Larger = fewer calls but a
    # single bad row poisons more work on retry.
    llm_batch_size: int = Field(default=20, alias="LLM_BATCH_SIZE")
    # Cosine similarity above which two conversations join the same theme. Model-
    # dependent: tuned for MiniLM. The hash embedder used in tests scores lower, so
    # tests override this rather than inheriting a threshold that would never cluster.
    cluster_threshold: float = Field(default=0.62, alias="CLUSTER_THRESHOLD")
    # How many themes to anonymize in parallel. Each theme is one LLM call. High enough
    # to hide latency, low enough not to trip a free-tier rate limit — backoff from a
    # 429 costs more than the parallelism saves.
    anonymize_concurrency: int = Field(default=4, alias="ANONYMIZE_CONCURRENCY")

    # Hard ceiling on Groq tokens for a single run. Once exceeded the run degrades to
    # heuristics rather than continuing to spend. Exists because a provider's daily
    # allowance is shared across every concurrent run on the same key, so one runaway run
    # can starve the others without anyone noticing. 0 disables the limit.
    max_tokens_per_run: int = Field(default=40000, alias="MAX_TOKENS_PER_RUN")

    # ---- Server ----------------------------------------------------------
    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8000, alias="API_PORT")
    mcp_port: int = Field(default=8001, alias="MCP_PORT")
    cors_origins: str = Field(default="http://localhost:3000", alias="CORS_ORIGINS")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Where uploaded conversation files and exported digests land.
    data_dir: str = Field(default="./data", alias="DATA_DIR")

    # Optional SQLite checkpoint mirror (aiosqlite). Empty disables it. Postgres stays
    # authoritative; this is a write-behind copy so run state survives losing the
    # primary database and can be inspected with the sqlite3 CLI.
    checkpoint_sqlite_path: str = Field(default="", alias="CHECKPOINT_SQLITE_PATH")

    # When Groq is missing or unavailable, fall back to keyword heuristics instead of
    # pausing. Output quality drops materially, so the digest states which stages ran
    # degraded. Set false to pause and wait for the key instead.
    allow_degraded_analysis: bool = Field(default=True, alias="ALLOW_DEGRADED_ANALYSIS")

    # When SuperDocs is missing or unavailable, render the digest locally rather than
    # pausing with the analysis stranded in the database.
    allow_local_render: bool = Field(default=True, alias="ALLOW_LOCAL_RENDER")

    @field_validator("superdocs_base_url", "groq_base_url")
    @classmethod
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def require_superdocs_key(self) -> str:
        """Return the SuperDocs key or raise with an actionable message.

        Called at the point of use, never at import, so the whole test suite and the
        offline stages of a run work with no key present.
        """
        if not self.superdocs_api_key:
            raise MissingCredentialError("SUPERDOCS_API_KEY", "SuperDocs operations")
        return self.superdocs_api_key

    def require_groq_key(self) -> str:
        if not self.groq_api_key:
            raise MissingCredentialError("GROQ_API_KEY", "LLM analysis")
        return self.groq_api_key

    def __repr__(self) -> str:  # pragma: no cover - defensive, not logic
        # Never let a settings dump leak a key into logs or a traceback.
        return (
            f"Settings(superdocs_base_url={self.superdocs_base_url!r}, "
            f"groq_model={self.groq_model!r}, "
            f"superdocs_api_key={'set' if self.superdocs_api_key else 'unset'}, "
            f"groq_api_key={'set' if self.groq_api_key else 'unset'})"
        )

    __str__ = __repr__


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()