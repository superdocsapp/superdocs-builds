"""Small injectable HTTP transport used by the SuperDocs adapter."""

from __future__ import annotations

import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str]
    body: bytes | None
    timeout_seconds: float


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class TransportTimeoutError(TimeoutError):
    """The external request exceeded its configured deadline."""


class TransportNetworkError(ConnectionError):
    """The external service could not be reached."""


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse:
        """Send one HTTP request."""


class UrllibHttpTransport:
    """Standard-library transport so the integration adds no HTTP dependency."""

    def send(self, request: HttpRequest) -> HttpResponse:
        outgoing = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with urllib.request.urlopen(
                outgoing, timeout=request.timeout_seconds
            ) as response:
                return HttpResponse(
                    status_code=response.status,
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            return HttpResponse(
                status_code=exc.code,
                headers={key.casefold(): value for key, value in exc.headers.items()},
                body=exc.read(),
            )
        except (socket.timeout, TimeoutError) as exc:
            raise TransportTimeoutError("The SuperDocs request timed out.") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise TransportNetworkError("The SuperDocs service could not be reached.") from exc
