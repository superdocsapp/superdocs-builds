"""Security primitives: file validation, prompt-injection defence, hashing.

Threat model for this system: uploaded documents are *untrusted input*. Text
extracted from a document is never allowed to act as an instruction to the LLM.
Two layers enforce that:

1. Detection — heuristic scan that flags injection-looking spans and records
   them as an audit event. Detection alone is not a control.
2. Containment — :func:`wrap_untrusted` fences document text inside an explicit
   delimiter and every prompt template states that fenced content is data.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from app.core.errors import FileTooLarge, UnsupportedFileType

UNTRUSTED_OPEN = "<<<UNTRUSTED_DOCUMENT_CONTENT>>>"
UNTRUSTED_CLOSE = "<<<END_UNTRUSTED_DOCUMENT_CONTENT>>>"

_INJECTION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("instruction_override", re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("instruction_override", re.compile(r"disregard\s+(the\s+)?(system|previous)\s+prompt", re.I)),
    ("role_hijack", re.compile(r"you\s+are\s+now\s+(a|an|the)\s+", re.I)),
    ("role_hijack", re.compile(r"^\s*(system|assistant)\s*:", re.I | re.M)),
    (
        "exfiltration",
        re.compile(
            r"(reveal|print|output|repeat)\s+(?:(?:your|the)\s+)?"
            r"(system\s+prompt|instructions|api\s*key)",
            re.I,
        ),
    ),
    ("tool_abuse", re.compile(r"\b(curl|wget|rm\s+-rf|subprocess|os\.system)\b", re.I)),
    ("delimiter_break", re.compile(re.escape(UNTRUSTED_CLOSE), re.I)),
    ("policy_override", re.compile(r"do\s+not\s+(report|flag)\s+(any\s+)?(conflicts?|discrepanc)", re.I)),
)


@dataclass(slots=True)
class InjectionScanResult:
    detected: bool = False
    matches: list[dict] = field(default_factory=list)

    @property
    def categories(self) -> list[str]:
        return sorted({m["category"] for m in self.matches})


def scan_for_injection(text: str) -> InjectionScanResult:
    """Heuristic prompt-injection scan over untrusted document text."""
    normalised = unicodedata.normalize("NFKC", text or "")
    result = InjectionScanResult()
    for category, pattern in _INJECTION_PATTERNS:
        for match in pattern.finditer(normalised):
            result.detected = True
            start = max(0, match.start() - 40)
            result.matches.append(
                {
                    "category": category,
                    "match": match.group(0)[:200],
                    "offset": match.start(),
                    "excerpt": normalised[start : match.end() + 40],
                }
            )
    return result


def wrap_untrusted(text: str) -> str:
    """Fence untrusted text and neutralise attempts to close the fence."""
    safe = (text or "").replace(UNTRUSTED_CLOSE, "[REDACTED_DELIMITER]")
    return f"{UNTRUSTED_OPEN}\n{safe}\n{UNTRUSTED_CLOSE}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_upload_filename(filename: str, *, allowed: tuple[str, ...]) -> str:
    """Validate and normalise an uploaded filename before streaming its bytes."""
    safe_name = Path(filename or "").name
    if not safe_name:
        raise UnsupportedFileType("Filename is missing")

    suffix = Path(safe_name).suffix.lower()
    if suffix not in allowed:
        raise UnsupportedFileType(
            f"Unsupported file type '{suffix}'", details={"allowed": list(allowed)}
        )
    return safe_name


def validate_upload(filename: str, data: bytes, *, max_mb: int, allowed: tuple[str, ...]) -> str:
    """Validate extension, size and non-emptiness. Returns a safe filename."""
    safe_name = validate_upload_filename(filename, allowed=allowed)
    if not data:
        raise UnsupportedFileType("Uploaded file is empty")
    if len(data) > max_mb * 1024 * 1024:
        raise FileTooLarge(f"File exceeds {max_mb}MB limit", details={"size": len(data)})
    return safe_name
