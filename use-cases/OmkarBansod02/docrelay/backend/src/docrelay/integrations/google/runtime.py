from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from pydantic import SecretStr

from docrelay.core.config import Settings
from docrelay.integrations.google.contracts import GoogleWriteBackPort
from docrelay.integrations.google.credentials import CredentialCipher
from docrelay.integrations.google.oauth import GoogleOAuthHTTPClient, GoogleOAuthPort
from docrelay.integrations.google.read_only import GoogleReadHTTPClient, GoogleReadPort
from docrelay.integrations.google.write_back import GoogleWriteHTTPClient


@dataclass(slots=True)
class GoogleRuntime:
    oauth: GoogleOAuthPort
    cipher: CredentialCipher
    client_id: str
    redirect_uri: str
    read_client_factory: Callable[[SecretStr], GoogleReadPort]
    write_client_factory: Callable[[SecretStr], GoogleWriteBackPort] | None = None
    close_callback: Callable[[], Awaitable[None]] | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "GoogleRuntime | None":
        if not settings.google_oauth_configured:
            return None
        client_id = settings.google_oauth_client_id
        client_secret = settings.google_oauth_client_secret
        redirect_uri = settings.google_oauth_redirect_uri
        keyring = settings.oauth_token_encryption_keys
        assert client_id is not None
        assert client_secret is not None
        assert redirect_uri is not None
        assert keyring is not None
        cipher = CredentialCipher.from_json_keyring(
            keyring.get_secret_value(),
            settings.oauth_token_encryption_primary_version,
        )
        http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.google_http_timeout_seconds),
            follow_redirects=False,
        )
        oauth = GoogleOAuthHTTPClient(
            http=http,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=redirect_uri,
        )
        return cls(
            oauth=oauth,
            cipher=cipher,
            client_id=client_id,
            redirect_uri=redirect_uri,
            read_client_factory=lambda token: GoogleReadHTTPClient(http=http, access_token=token),
            write_client_factory=lambda token: GoogleWriteHTTPClient(http=http, access_token=token),
            close_callback=http.aclose,
        )

    async def close(self) -> None:
        if self.close_callback is not None:
            await self.close_callback()
