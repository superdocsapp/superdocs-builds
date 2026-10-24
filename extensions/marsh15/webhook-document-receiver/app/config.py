from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    superdocs_api_key: SecretStr
    webhook_secret: SecretStr = Field(min_length=32)
    github_webhook_secret: SecretStr = Field(min_length=32)
    management_token: SecretStr = Field(min_length=32)
    management_actor_id: str = "operator"
    routes_path: str = "routes/routes.yaml"
    templates_path: str = "templates"
    database_url: str = "postgresql://postgres:postgres@localhost:5432/webhook_receiver"
    database_pool_max_size: int = Field(default=10, ge=1, le=50)
    worker_lease_seconds: int = Field(default=600, ge=10, le=3600)
    worker_poll_interval_seconds: float = Field(default=1, ge=0.1, le=60)
    worker_max_retries: int = Field(default=3, ge=0, le=10)
    retry_base_seconds: float = Field(default=2, ge=0.1, le=60)
    retry_max_seconds: float = Field(default=300, ge=1, le=3600)
    max_artifact_bytes: int = Field(default=10_485_760, ge=1024, le=10_485_760)
    signature_tolerance_seconds: int = Field(default=300, ge=30, le=3600)
    max_body_bytes: int = Field(default=1_048_576, ge=1024, le=10_485_760)
    max_json_depth: int = Field(default=20, ge=2, le=100)
    max_json_nodes: int = Field(default=10_000, ge=100, le=100_000)
    initial_route_id: str = "incident-report"
    initial_route_event_type: str = "incident.resolved"
    initial_route_version: str = "t2-a-v1"
    initial_route_fields: str = "type,incident_id,title,summary,resolved_at"
    initial_route_approval_mode: Literal["manual", "automatic"] = "manual"
    export_format: str = "docx"
    document_instruction: str = (
        "Create a concise event report. State only facts present in the event payload."
    )
    superdocs_base_url: str = "https://api.superdocs.app"
    superdocs_timeout_seconds: float = Field(default=180, ge=1, le=600)
    job_poll_interval_seconds: float = 2
    job_timeout_seconds: float = 600

    @model_validator(mode="after")
    def lease_covers_external_request_sequence(self) -> "Settings":
        parsed = urlparse(self.superdocs_base_url)
        loopback_hosts = {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme != "https" and parsed.hostname not in loopback_hosts:
            raise ValueError(
                "SUPERDOCS_BASE_URL must use HTTPS unless it targets a loopback host"
            )
        minimum = 3 * self.superdocs_timeout_seconds + 30
        if self.worker_lease_seconds < minimum:
            raise ValueError(
                "WORKER_LEASE_SECONDS must be at least three SuperDocs request timeouts plus 30 seconds"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
