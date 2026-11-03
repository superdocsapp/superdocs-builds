from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class GatewaySettings(BaseSettings):
    superdocs_api_url: str = "https://api.superdocs.app"
    superdocs_api_key: str
    gateway_policy_file: Path = ROOT_DIR / "config" / "gateway_policy.yaml"
    request_timeout_seconds: float = 60.0

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


gateway_settings = GatewaySettings()
