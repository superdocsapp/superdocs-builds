"""
Fake SuperDocs client used by the test suite.

This client performs no network calls and does not require a live API key.

It records:
    - chat calls
    - document-list calls
    - image uploads
    - document persistence
    - exports

It also records call_order so tests can verify that deterministic content
is persisted before the AI narrative call.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FakeChatResult:
    response_text: str
    updated_html: str | None = None
    version_id: str | None = "fake-version-1"
    monthly_remaining: int | None = 9999


class FakeSuperDocsClient:
    def __init__(self):
        self.chat_calls: list[dict] = []
        self.persist_calls: list[dict] = []
        self.upload_calls: list[dict] = []
        self.export_calls: list[dict] = []

        self.list_documents_calls: list[dict] = []

        self.call_order: list[str] = []

        # session_id -> accumulated HTML
        self.documents: dict[str, str] = {}

        self._version_counter = 0

    def chat(
        self,
        message,
        session_id,
        document_html=None,
        approval_mode="approve_all",
        model_tier=None,
    ):
        self.call_order.append("chat")

        self.chat_calls.append(
            {
                "message": message,
                "session_id": session_id,
                "document_html": document_html,
                "approval_mode": approval_mode,
                "model_tier": model_tier,
            }
        )

        self._version_counter += 1

        existing = self.documents.get(
            session_id,
            document_html or "",
        )

        appended = (
            existing
            + f"<p data-fake-ai-narrative>"
            f"[AI narrative for: {message[:40]}...]"
            f"</p>"
        )

        self.documents[session_id] = appended

        return FakeChatResult(
            response_text="ok",
            updated_html=appended,
            version_id=f"v{self._version_counter}",
        )

    def list_session_documents(
        self,
        session_id,
    ):
        self.call_order.append("list_documents")

        self.list_documents_calls.append(
            {
                "session_id": session_id,
            }
        )

        if session_id in self.documents:
            return [
                {
                    "durable_document_id": (
                        f"doc-{session_id}"
                    ),
                    "id": "doc_primary",
                }
            ]

        return []

    def persist_document(
        self,
        session_id,
        document_id,
        html,
    ):
        self.call_order.append("persist")

        self.persist_calls.append(
            {
                "session_id": session_id,
                "html": html,
                "document_id": document_id,
            }
        )

        existing = self.documents.get(
            session_id,
            "",
        )

        self.documents[session_id] = (
            existing + html
        )

        return {
            "document_id": document_id,
            "status": "saved",
        }

    def upload_image(
        self,
        png_bytes,
        filename="chart.png",
    ):
        self.call_order.append("upload")

        self.upload_calls.append(
            {
                "filename": filename,
                "size": len(png_bytes),
            }
        )

        return (
            "https://fake.superdocs.app/images/"
            f"{filename}"
        )

    def export(
        self,
        *,
        session_id=None,
        html=None,
        fmt="docx",
        filename=None,
    ):
        self.call_order.append("export")

        self.export_calls.append(
            {
                "session_id": session_id,
                "html": html,
                "fmt": fmt,
                "filename": filename,
            }
        )

        content = self.documents.get(
            session_id,
            html or "",
        )

        return (
            f"FAKE-DOCX:{fmt}:{len(content)}"
        ).encode()