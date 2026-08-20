"""Customer-identity redaction for the shared Quarterly Competitive Brief.

Two layers (architecture.md §5):

1. `build_redacted_context()` -- constructs the DebriefRef objects sent to the AI for
   synthesis with customer names structurally substituted for [CUSTOMER] BEFORE they
   ever reach a prompt. The model is never given the real name for this call.
2. `scan_for_leaks()` -- a post-hoc, independent scan of the exported brief text
   against every known customer name/alias. This is the "verifiable" part: it runs
   after generation, against the actual output bytes, and BLOCKS export on a hit.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

from .templates import DebriefRef

CUSTOMER_PLACEHOLDER = "[CUSTOMER]"


def extract_text_from_file(path: Path) -> str:
    """Best-effort text extraction for the standalone `redact-check` CLI command.

    Supports .docx (via the OOXML document.xml inside the zip -- no extra
    dependency needed for this one-way text pull), and plain text formats
    (.html, .md, .txt) as-is. Anything else (e.g. .pdf) raises a clear error
    rather than silently scanning garbage bytes and reporting a false "clean".
    """
    suffix = path.suffix.lower()
    if suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
        # Strip XML tags to plain text; good enough for a substring redaction scan.
        text = re.sub(r"<[^>]+>", " ", xml)
        return re.sub(r"\s+", " ", text)
    if suffix in (".html", ".htm", ".md", ".txt", ""):
        return path.read_text(errors="ignore")
    raise ValueError(
        f"redact-check does not support {suffix} files directly. Export the brief "
        "as .docx, .html, .md, or .txt and check that instead."
    )


class RedactionBlockedExport(RuntimeError):
    """Raised when scan_for_leaks finds a customer identifier in export-bound text."""


def redact_text(text: str, customer_names: list[str]) -> str:
    """Replace every occurrence (case-insensitive, whole-word-ish) of a known
    customer name/alias with the placeholder. Used when building evidence snippets
    for the synthesis prompt so real names never enter the AI context."""
    redacted = text
    for name in sorted((n for n in customer_names if n), key=len, reverse=True):
        pattern = re.compile(re.escape(name), re.IGNORECASE)
        redacted = pattern.sub(CUSTOMER_PLACEHOLDER, redacted)
    return redacted


def build_redacted_context(
    deal_records: list[dict],
) -> list[DebriefRef]:
    """deal_records: list of index records (see index.py Record).

    Each record's `customer_name` and any aliases are used ONLY to redact its own
    evidence_snippets -- the name itself is never placed in the returned DebriefRef.
    """
    refs: list[DebriefRef] = []
    for rec in deal_records:
        names = [rec.get("customer_name", "")] + list(rec.get("customer_aliases", []) or [])
        redacted_snippets = [redact_text(s, names) for s in rec.get("evidence_snippets", [])]
        refs.append(
            DebriefRef(
                deal_code=rec["deal_code"],
                outcome=rec["outcome"],
                segment=rec["segment"],
                competitors=list(rec.get("competitors", [])),
                evidence_snippets=redacted_snippets,
            )
        )
    return refs


@dataclass
class RedactionScanResult:
    ok: bool
    leaked_terms: list[str] = field(default_factory=list)

    def raise_if_leaked(self, document_label: str) -> None:
        if not self.ok:
            raise RedactionBlockedExport(
                f"{document_label} export BLOCKED: found customer identifier(s) "
                f"{self.leaked_terms} in the generated text. Not writing the file. "
                "This is the redaction gate described in architecture.md §5 -- it "
                "means either a customer name leaked through the AI's synthesis, or "
                "a false positive from a name that is also a common word (check "
                "the term list before overriding)."
            )


def scan_for_leaks(html_or_text: str, banned_terms: list[str]) -> RedactionScanResult:
    """Scan text (or HTML -- text is extracted first) for any banned term.

    banned_terms should be every known customer_name + customer_aliases across the
    full index, not just the quarter being exported, since evidence text could in
    principle reference another deal's customer.
    """
    if "<" in html_or_text and ">" in html_or_text:
        text = BeautifulSoup(html_or_text, "html.parser").get_text(" ")
    else:
        text = html_or_text
    normalized = re.sub(r"\s+", " ", text).lower()

    leaked = []
    for term in banned_terms:
        if not term or len(term.strip()) < 3:
            continue  # too short to check safely (avoid pathological false positives)
        if term.strip().lower() in normalized:
            leaked.append(term)
    return RedactionScanResult(ok=not leaked, leaked_terms=leaked)
