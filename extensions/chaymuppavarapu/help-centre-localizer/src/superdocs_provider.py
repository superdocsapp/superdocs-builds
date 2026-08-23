import os
import uuid

import requests


class SuperDocsLocalizationProvider:
    """SuperDocs API-backed localization provider."""

    BASE_URL = "https://api.superdocs.app"

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("SUPERDOCS_API_KEY")
        if not self.api_key:
            raise RuntimeError("SUPERDOCS_API_KEY is not set.")

    def translate(self, text: str, locale: str) -> str:
        """Translate one paragraph/text unit using the SuperDocs chat API."""
        message = f"""
Translate the following help-centre content into {locale}.

Rules:
1. Translate every human-readable sentence and UI label.
2. Do not leave ordinary English text untranslated.
3. Keep the product name "SuperDocs" exactly unchanged.
4. Keep keyboard shortcuts such as "Ctrl + K" exactly unchanged.
5. Keep code such as "npm install" exactly unchanged.
6. Translate the surrounding sentence containing protected content.
7. Return only the translated content, with no explanation.

Target locale:
{locale}

Content:
{text}
""".strip()

        data = self._post(
            message=message,
            document_html=text,
            timeout=60,
        )
        return self._extract_response(data)

    def translate_html(self, html: str, locale: str) -> str:
        """Translate an HTML fragment when a caller explicitly needs HTML output."""
        message = f"""
Translate the following help-centre HTML fragment into {locale}.

Rules:
1. Translate every human-readable sentence and UI label.
2. Keep "SuperDocs", keyboard shortcuts, and code unchanged.
3. Preserve the HTML structure and all attributes.
4. Preserve data-chunk-id attributes.
5. Do not add, remove, duplicate, or nest HTML elements.
6. Return only the localized HTML fragment.

Target locale:
{locale}

HTML:
{html}
""".strip()

        data = self._post(
            message=message,
            document_html=html,
            timeout=60,
        )
        return self._extract_html(data)

    def _post(self, message: str, document_html: str, timeout: int) -> dict:
        session_id = f"localizer-{uuid.uuid4()}"
        response = requests.post(
            f"{self.BASE_URL}/v1/chat",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "message": message,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": "approve_all",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _extract_response(data: dict) -> str:
        """Extract the plain translation returned by the chat API."""
        result = data.get("response")
        if not isinstance(result, str) or not result.strip():
            raise RuntimeError(
                "SuperDocs response did not contain a usable translated response."
            )
        return result.strip()

    @staticmethod
    def _extract_html(data: dict) -> str:
        """Extract localized HTML from document_changes.updated_html."""
        try:
            updated_html = data["document_changes"]["updated_html"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(
                "SuperDocs response did not contain document_changes.updated_html."
            ) from exc

        if not isinstance(updated_html, str):
            raise RuntimeError("SuperDocs returned a non-string updated_html.")
        return updated_html
