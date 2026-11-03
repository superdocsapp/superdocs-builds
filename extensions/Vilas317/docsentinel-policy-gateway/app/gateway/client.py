import httpx

from app.gateway.config import gateway_settings


class DownstreamUnavailableError(Exception):
    """Raised when SuperDocs cannot be reached."""


class SuperDocsClient:
    def __init__(self) -> None:
        self.base_url = gateway_settings.superdocs_api_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {gateway_settings.superdocs_api_key}"}

    async def request(self, *, method: str, path: str,
                      json: dict | None = None,
                      files: dict | None = None) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=gateway_settings.request_timeout_seconds) as client:
                return await client.request(
                    method=method,
                    url=f"{self.base_url}{path}",
                    headers=self.headers,
                    json=json,
                    files=files,
                )
        except httpx.RequestError as exc:
            raise DownstreamUnavailableError("SuperDocs is unavailable.") from exc
