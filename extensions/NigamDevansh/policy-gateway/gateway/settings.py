from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    upstream_url: str = "https://api.superdocs.app/mcp"
    listen_port: int = 8080

    # Absent policy file → transparent passthrough, which is Milestone 1's
    # behaviour and a legitimate way to run this. Enforcement is opt-in.
    policy_path: str = "policy.yml"
    audit_log_path: str = "data/audit.jsonl"

    model_config = {"env_prefix": "GATEWAY_"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
