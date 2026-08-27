"""Post-draft verification: prove the content actually landed, don't assume it.

This module exists because of a real failure caught by a real run. SuperDocs
returned a completed job whose response said "0 of 4 asked could be completed",
the document was never populated — and the drafter cheerfully printed
"Drafted: out/verify-final.docx" and recorded it as done. A success message that
isn't true is the one output this tool must never produce.

So "done" is no longer "the job status said completed". It is: the exported file
on disk demonstrably contains the engineer's facts. Counted, not claimed.
"""
from __future__ import annotations

import html
import os
import re
import zipfile
from dataclasses import dataclass

from .models import DraftRequest


@dataclass
class VerificationResult:
    checked: int
    missing: list[str]
    readable: bool = True
    note: str = ""

    @property
    def ok(self) -> bool:
        # An unreadable format can't be verified either way — that's reported
        # honestly rather than counted as a pass or forced into a failure.
        return self.readable and not self.missing


#: How much of a narrative field to use as a verification anchor. Long enough to
#: be distinctive, short enough to tolerate harmless reflow by the editor.
_ANCHOR_LEN = 60


def _norm(text: str) -> str:
    """Collapse whitespace and resolve HTML entities, so a fact and the document
    text are compared on equal terms (`&` survives a round trip as `&amp;`)."""
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def expected_facts(req: DraftRequest) -> list[str]:
    """The data-derived facts that must appear in a correct draft, on any
    customer's template.

    **Mirrors exactly what `render.py` emits for this `document_type`** — an
    8D-only document legitimately contains no FMEA table, so demanding one back
    would fail a perfectly good draft. That is not hypothetical: an earlier
    version of this function expected every fact regardless of document type,
    because it was written against the one `combined` example it was developed
    on. The first run with `document_type: 8d` rejected a correct document. A
    verifier that wrongly refuses valid work is worse than no verifier, so the
    two now move together — see `render.render_content_block`.

    Deliberately drawn from the input model rather than the output text, and
    deliberately not a raw digit scan: a template's own boilerplate contains
    numbers too (one says "1-10 AIAG-VDA scale", another doesn't), and those are
    presentation, not data.
    """
    facts: list[str] = []

    if req.document_type in ("fmea", "combined"):
        for fm in req.failure_modes:
            facts.append(fm.id)
            rpn = fm.rpn()
            if rpn is not None:
                facts.append(str(rpn))
        for a in req.actions:
            facts.append(a.id)
            if a.target_date:
                facts.append(a.target_date)

    if req.document_type in ("ppap", "combined") and req.ppap:
        facts.append(req.ppap.part_number)

    if req.document_type in ("8d", "combined") and req.eightd:
        # The 8D output is narrative, so anchor on the opening of the two fields
        # validate.py already treats as mandatory. render.py emits them verbatim.
        for value in (req.eightd.d2_problem_description, req.eightd.d4_root_cause):
            if value.strip():
                facts.append(_norm(value)[:_ANCHOR_LEN])

    return facts


def _extract_text(path: str) -> tuple[str, bool, str]:
    """Return (text, readable, note). Dependency-free: a .docx is a zip, so its
    body XML can be read without pulling in python-docx just to verify."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".docx":
        try:
            with zipfile.ZipFile(path) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            # Strip tags so text split across runs still matches as one string.
            return re.sub(r"<[^>]+>", "", xml), True, ""
        except (zipfile.BadZipFile, KeyError, OSError) as e:
            return "", False, f"could not read .docx body ({e})"
    if ext in (".md", ".markdown", ".txt", ".html", ".htm"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(), True, ""
        except OSError as e:
            return "", False, f"could not read file ({e})"
    return "", False, f"no text extractor for '{ext}' — verification skipped, not passed"


def verify_export(export_path: str, req: DraftRequest) -> VerificationResult:
    facts = expected_facts(req)
    text, readable, note = _extract_text(export_path)
    if not readable:
        return VerificationResult(checked=len(facts), missing=[], readable=False, note=note)
    normalized = _norm(text)
    missing = [f for f in facts if _norm(f) not in normalized]
    return VerificationResult(checked=len(facts), missing=missing, readable=True)


def document_was_modified(job_result: dict, original_html: str) -> bool:
    """Did the turn actually change the document?

    SuperDocs can return a *completed* job whose every operation failed — the
    honest signal is whether updated_html exists and differs from what we sent,
    not whether the status string says 'completed'.
    """
    changes = job_result.get("document_changes")
    if not isinstance(changes, dict):
        return False
    updated = changes.get("updated_html")
    if not updated:
        return False
    return updated.strip() != (original_html or "").strip()
