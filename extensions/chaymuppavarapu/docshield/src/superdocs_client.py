from __future__ import annotations

from dataclasses import dataclass
import os

import requests


@dataclass(frozen=True)
class SuperDocsResponse:
    html: str
    raw: dict


class SuperDocsAPIError(RuntimeError):
    """Raised when the SuperDocs API cannot complete a request."""


class SuperDocsClient:
    """
    Minimal client for the SuperDocs document API.

    The client is intentionally isolated from parsing and validation so
    the rest of DocShield can be tested without a live API key.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.superdocs.app",
        timeout: float = 60.0,
    ) -> None:
        self.api_key = (
            api_key
            or os.getenv("SUPERDOCS_API_KEY")
        )

        if not self.api_key:
            raise ValueError(
                "SUPERDOCS_API_KEY is required."
            )

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def edit(
        self,
        html: str,
        instruction: str,
    ) -> SuperDocsResponse:
        """
        Ask SuperDocs to edit an HTML document.

        The exact endpoint/payload can be configured without changing
        the DocShield validation pipeline.
        """

        url = f"{self.base_url}/v1/documents"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        payload = {
            "html": html,
            "instruction": instruction,
        }

        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise SuperDocsAPIError(
                f"SuperDocs request failed: {exc}"
            ) from exc

        if not response.ok:
            raise SuperDocsAPIError(
                "SuperDocs API returned "
                f"HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise SuperDocsAPIError(
                "SuperDocs API returned invalid JSON."
            ) from exc

        html_result = self._extract_html(data)

        if not html_result:
            raise SuperDocsAPIError(
                "SuperDocs response did not contain edited HTML."
            )

        return SuperDocsResponse(
            html=html_result,
            raw=data,
        )

    @staticmethod
    def _extract_html(data: object) -> str | None:
        """
        Extract edited HTML from common response shapes.

        We keep this tolerant because the API response envelope may
        evolve independently of DocShield.
        """

        if not isinstance(data, dict):
            return None

        candidates = [
            data.get("html"),
            data.get("content"),
            data.get("document"),
        ]

        for value in candidates:
            if isinstance(value, str):
                return value

            if isinstance(value, dict):
                nested = (
                    value.get("html")
                    or value.get("content")
                )

                if isinstance(nested, str):
                    return nested

        result = data.get("result")

        if isinstance(result, dict):
            nested = (
                result.get("html")
                or result.get("content")
            )

            if isinstance(nested, str):
                return nested

        return None
