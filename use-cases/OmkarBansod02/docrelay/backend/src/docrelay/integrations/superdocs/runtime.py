from dataclasses import dataclass

import httpx

from docrelay.core.config import Settings
from docrelay.integrations.superdocs.client import SuperDocsHTTPClient


@dataclass(slots=True)
class SuperDocsRuntime:
    client: SuperDocsHTTPClient
    http: httpx.AsyncClient

    @classmethod
    def from_settings(cls, settings: Settings) -> "SuperDocsRuntime | None":
        if settings.superdocs_api_key is None:
            return None
        http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.superdocs_http_timeout_seconds),
            follow_redirects=False,
        )
        return cls(
            client=SuperDocsHTTPClient(
                http=http,
                api_key=settings.superdocs_api_key,
                api_base=settings.superdocs_api_base,
            ),
            http=http,
        )

    async def close(self) -> None:
        await self.http.aclose()
