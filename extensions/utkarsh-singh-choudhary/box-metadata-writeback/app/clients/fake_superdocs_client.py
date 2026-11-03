"""In-memory SuperDocs client for offline tests and local demo runs.

Simulates the real API's documented quirk (proposed_change arrives as a
JSON-encoded string) so app/clients/superdocs_client.parse_proposed_change
is exercised the same way it would be against the live API. Instruction
handling is a small deterministic rule set, not an LLM -- enough to drive
the pipeline's control flow (classify -> extract -> generate companion ->
normalize) through realistic-shaped responses without needing a live key,
per the brief's "real tests that run without a live key" requirement.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from app.clients.superdocs_client import ChatResult, SuperDocsAPIError, SuperDocsClient


class FakeSuperDocsClient(SuperDocsClient):
    def __init__(self) -> None:
        self._docs: dict[str, bytes] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._approved: dict[str, bool] = {}
        # Test hook: force the next chat() call to raise, to exercise
        # graceful-degradation paths the same way a real outage would.
        self._force_failure = False
        self._force_failures_remaining = 0
        # Test hook: records every instruction passed to chat(), so tests
        # can assert exactly which stages actually ran against SuperDocs
        # (as opposed to being replayed from a checkpoint) -- e.g. proving
        # a resumed run does NOT re-call classify/extract.
        self.call_log: list[str] = []

    def force_next_failure(self) -> None:
        self._force_failure = True

    def force_next_n_failures(self, n: int) -> None:
        """Fails the next n chat() calls in a row before letting one
        through -- used to prove retry-with-backoff genuinely retries
        (recovers within budget) as distinct from eventually giving up
        (exhausts budget), rather than only ever testing a single
        transient blip."""
        self._force_failures_remaining = n

    def upload(self, filename: str, content: bytes) -> str:
        doc_id = f"doc-{uuid.uuid4().hex[:8]}"
        self._docs[doc_id] = content
        return doc_id

    def chat(self, document_id: str, instruction: str) -> ChatResult:
        self.call_log.append(instruction)
        if self._force_failure:
            self._force_failure = False
            raise SuperDocsAPIError("simulated SuperDocs outage")
        if self._force_failures_remaining > 0:
            self._force_failures_remaining -= 1
            raise SuperDocsAPIError("simulated SuperDocs outage")
        if document_id not in self._docs:
            raise SuperDocsAPIError(f"unknown document {document_id}")

        content = self._docs[document_id].decode(errors="ignore")
        session_id = f"sess-{uuid.uuid4().hex[:8]}"

        proposed: Optional[dict[str, Any]] = None
        message = ""

        if "classify" in instruction.lower():
            doc_class, confidence = _classify(content)
            message = f"This document appears to be a {doc_class}."
            proposed = {"doc_class": doc_class, "confidence": confidence}
        elif "extract key terms" in instruction.lower():
            fields, confidence = _extract(content)
            message = "Extracted the fields I could support from the source text."
            proposed = {"fields": fields, "field_confidence": confidence}
        elif "companion document" in instruction.lower():
            companion_text = _generate_companion(content)
            message = "Drafted the companion document."
            proposed = {"companion_text": companion_text}
        elif "normalize" in instruction.lower():
            normalized_text = _normalize(content)
            message = "Normalized to the retention-approved template."
            proposed = {"normalized_text": normalized_text}
        else:
            message = "Instruction not recognized."
            proposed = None

        # Simulate the real API's documented behavior: proposed_change
        # travels as a JSON-encoded string, not a dict.
        raw_proposed = json.dumps(proposed) if proposed is not None else None

        self._sessions[session_id] = {
            "document_id": document_id,
            "raw_proposed": raw_proposed,
        }
        from app.clients.superdocs_client import parse_proposed_change

        return ChatResult(
            session_id=session_id,
            raw_message=message,
            proposed_change=parse_proposed_change(raw_proposed),
        )

    def approve(self, document_id: str, session_id: str) -> None:
        if session_id not in self._sessions:
            raise SuperDocsAPIError(f"unknown session {session_id}")
        if self._sessions[session_id]["document_id"] != document_id:
            raise SuperDocsAPIError("session/document mismatch")
        self._approved[session_id] = True

    def export(self, document_id: str) -> bytes:
        return self._docs.get(document_id, b"")


# --- deterministic "model" stand-ins, enough to drive real control flow ----------

def _has_word(pattern: str, lowered: str) -> bool:
    """Word-boundary match, not substring match. A naive `"contract" in
    lowered` check matches "contracts", "subcontractor", "recontracted"
    -- any word that happens to contain the keyword as a substring, not
    just an actual standalone use of it. Found live: a synthetic demo
    document's own disclaimer footer ("...contracts in the first
    batch...") tripped the old substring check and got the document
    misclassified as a contract. \b\bpattern\b\b closes the whole class
    of that bug (any keyword, any surrounding word), not just the one
    sentence that surfaced it -- the same fix shape as the earlier
    policy/agreement negation bug, applied one level deeper."""
    return re.search(rf"\b{re.escape(pattern)}\b", lowered) is not None


def _classify(content: str) -> tuple[str, float]:
    lowered = content.lower()
    if _has_word("invoice", lowered) or "amount due" in lowered:
        return "invoice", 0.92
    if _has_word("amendment", lowered):
        return "amendment", 0.88
    if _has_word("policy", lowered):
        return "policy", 0.75
    if _has_word("agreement", lowered) or _has_word("contract", lowered):
        return "contract", 0.9
    if _has_word("letter", lowered) or _has_word("memo", lowered) or "dear " in lowered or "regards," in lowered:
        return "correspondence", 0.7
    return "unknown", 0.2


def _extract(content: str) -> tuple[dict[str, Any], dict[str, float]]:
    """Pulls only what the fake 'source text' actually states, and leaves
    everything else out -- this is what lets the pipeline test "left empty
    rather than guessed" honestly rather than by construction.

    Also returns a per-field confidence, standing in for what a real
    extraction model would report. Confidence is deliberately uneven here
    (monetary values lower than clean labeled dates) so the review-queue
    path in the pipeline has something realistic to exercise, not just a
    hand-picked forced-low-confidence test fixture.
    """
    fields: dict[str, Any] = {}
    confidence: dict[str, float] = {}
    for line in content.splitlines():
        line = line.strip()
        if line.lower().startswith("counterparty:"):
            fields["counterparty_name"] = line.split(":", 1)[1].strip()
            confidence["counterparty_name"] = 0.93
        elif line.lower().startswith("effective date:"):
            fields["effective_date"] = line.split(":", 1)[1].strip()
            confidence["effective_date"] = 0.95
        elif line.lower().startswith("expiration date:"):
            fields["expiration_date"] = line.split(":", 1)[1].strip()
            confidence["expiration_date"] = 0.95
        elif line.lower().startswith("value:"):
            fields["contract_value"] = line.split(":", 1)[1].strip()
            # Monetary figures are the field type this fake model is
            # least sure about -- realistic stand-in for OCR/formatting
            # ambiguity, and deliberately below the 0.7 review threshold
            # so this path is genuinely exercised, not just claimed.
            confidence["contract_value"] = 0.55
    return fields, confidence


def _generate_companion(content: str) -> str:
    return f"COMPANION SUMMARY\n---\nAuto-generated from source document.\n\n{content[:300]}"


def _normalize(content: str) -> str:
    return "[RETENTION-APPROVED TEMPLATE]\n" + content
