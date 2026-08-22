"""
Deterministic stand-in for SuperDocsClient, same interface, no network/key required. Mirrors the FakeLLM
pattern from Task 1 for the same reason: the adaptation/verification/revision logic needs to be provably
correct independent of what a real model happens to do on a given day.

Behavior is scripted per-session: `chat()` looks up a response function keyed by a substring of the
instruction, applies it to the tracked document HTML for that session, and returns the new HTML. This lets
tests express "the fake AI simplifies chunk c2's text" or "the fake AI accidentally corrupts a protected
chunk" (to prove the verifier catches it) without needing a real model to cooperate.
"""
from __future__ import annotations

from typing import Callable, Optional

from bs4 import BeautifulSoup


class FakeSuperDocsClient:
    def __init__(self):
        self.sessions: dict[str, str] = {}  # session_id -> current document html
        self.chat_log: list[tuple[str, str]] = []  # (session_id, message)
        self.scripted_edits: dict[str, Callable[[str], str]] = {}
        # keyed by a substring that must appear in the chat message

    def script_edit(self, message_substring: str, transform: Callable[[str], str]):
        """Register a fake AI behavior: whenever a chat message contains `message_substring`, `transform`
        is applied to the session's current HTML to produce the new HTML."""
        self.scripted_edits[message_substring] = transform

    def upload_document(self, filepath: str, session_id: str):
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        self.sessions[session_id] = html
        from src.client import ChunkedDocument
        return ChunkedDocument(html=html, session_id=session_id, chunks_count=html.count("data-chunk-id"), version_id="v_fake1")

    def load_html(self, session_id: str, html: str):
        """Test convenience: seed a session directly with HTML rather than reading a file."""
        self.sessions[session_id] = html

    def chat(self, session_id: str, message: str, document_html: Optional[str] = None) -> dict:
        self.chat_log.append((session_id, message))
        if document_html is not None:
            self.sessions[session_id] = document_html

        current = self.sessions.get(session_id, "")
        updated = current
        for substring, transform in self.scripted_edits.items():
            if substring in message:
                updated = transform(current)
                break

        self.sessions[session_id] = updated
        return {
            "response": f"[fake ai] applied edit for: {message[:60]}",
            "document_changes": {"updated_html": updated},
        }

    def export(self, session_id: str, fmt: str = "docx", filename: Optional[str] = None) -> bytes:
        html = self.sessions.get(session_id, "")
        # Fake export just returns the HTML as bytes with a marker -- good enough to assert content made
        # it through the pipeline without needing a real docx renderer in the test suite.
        return f"FAKE_EXPORT[{fmt}]\n{html}".encode()

    def load_html_as_document(self, session_id: str, html: str) -> None:
        """Mirrors the real client's sync-before-export method: overwrites the session's tracked html
        directly, verbatim -- no AI transform applied, matching the real 'verbatim load' semantics."""
        self.sessions[session_id] = html


def default_simplify_transform(protected_chunk_ids: set[str]):
    """A reference fake-AI transform: rewrites the text of every PROSE chunk (wraps it to mark it
    'simplified'), leaves every chunk in `protected_chunk_ids` byte-identical. Used by tests that want a
    well-behaved fake AI, as a baseline before testing the misbehaving case."""

    def _transform(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(attrs={"data-chunk-id": True}):
            cid = tag.get("data-chunk-id")
            if cid in protected_chunk_ids:
                continue
            for text_node in tag.find_all(string=True):
                if text_node.strip():
                    text_node.replace_with(f"[simplified] {text_node.strip()}")
        return str(soup)

    return _transform


def corrupting_transform(protected_chunk_ids: set[str], corrupt_chunk_id: str):
    """A reference fake-AI transform that MISBEHAVES: it also rewrites one protected chunk, simulating a
    real model ignoring instructions. Used to prove the verifier actually catches this rather than trusting
    the AI's compliance."""

    def _transform(html: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(attrs={"data-chunk-id": True}):
            cid = tag.get("data-chunk-id")
            should_edit = cid not in protected_chunk_ids or cid == corrupt_chunk_id
            if not should_edit:
                continue
            for text_node in tag.find_all(string=True):
                if text_node.strip():
                    text_node.replace_with(f"[simplified] {text_node.strip()}")
        return str(soup)

    return _transform
