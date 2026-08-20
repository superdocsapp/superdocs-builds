"""Client for the four SuperDocs REST calls this build is built against:
upload, chat (edit instruction), approve, export.

Per the task brief: "proposed-change content arrives as a JSON-encoded
string and needs a second parse" -- _parse_proposed_change below does
that second parse so callers never see the raw double-encoded string.

This module is transport-only. All document intelligence (classification,
extraction, companion-doc generation, normalization prompts) lives in
app/workflow/pipeline.py, which calls chat() with a specific instruction
per stage and interprets the structured result.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


class SuperDocsAPIError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        # HTTP status code from the real API response, when known. None
        # for errors that never got a response at all (connection
        # refused, DNS failure, read timeout) or for the fake client's
        # simulated failures, which don't carry a status code.
        self.status_code = status_code


@dataclass
class ChatResult:
    session_id: str
    raw_message: str
    proposed_change: Optional[dict[str, Any]]  # already-parsed, never the raw JSON string


class SuperDocsClient(ABC):
    @abstractmethod
    def upload(self, filename: str, content: bytes) -> str:
        """Returns a SuperDocs document_id."""
        ...

    @abstractmethod
    def chat(self, document_id: str, instruction: str) -> ChatResult:
        ...

    @abstractmethod
    def approve(self, document_id: str, session_id: str) -> None:
        ...

    @abstractmethod
    def export(self, document_id: str) -> bytes:
        ...


def parse_proposed_change(raw: Any) -> Optional[dict[str, Any]]:
    """SuperDocs sends proposed_change as a JSON-encoded string inside the
    chat response; this is the "second parse" the task doc warns about.
    Missing it is, per the brief, the #1 reason integrators see empty diff
    cards. We handle both the double-encoded string form and an
    already-decoded dict defensively, since the docs note this has been a
    source of confusion for other integrators and we would rather be
    lenient here than silently drop data.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None
    return None
