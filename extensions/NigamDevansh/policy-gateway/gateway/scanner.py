from __future__ import annotations

import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field

_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

TEXT_SCAN_FIELDS: dict[str, tuple[str, ...]] = {
    "chat": ("message", "document_html"),
    "chat_async": ("message", "document_html"),
    "export_document": ("html",),
}

BASE64_SCAN_FIELDS: dict[str, tuple[str, ...]] = {
    "upload_document_base64": ("file_base64",),
    "upload_attachment_base64": ("file_base64",),
    "upload_template_base64": ("file_base64",),
    "upload_image_base64": ("image_base64",),
}


@dataclass(frozen=True)
class ScanMatch:
    rule: str
    field: str
    start: int
    end: int
    matched: str


@dataclass
class ScanResult:
    matches: list[ScanMatch] = field(default_factory=list)


BUILTIN_RULES: dict[str, re.Pattern[str]] = {
    "pii_email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "pii_ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "secret_api_key": re.compile(r"(?:sk|pk|api|key|secret|token)[-_][a-zA-Z0-9_-]{20,}"),
    "injection_markers": re.compile(
        r"(?i)"
        r"(?:ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions)"
        r"|(?:you\s+are\s+now\s+(?:a|an|the)\s+)"
        r"|(?:system\s*:\s*you\s+are)"
        r"|(?:forget\s+(?:all\s+)?(?:previous|prior)\s+)"
        r"|(?:disregard\s+(?:all\s+)?(?:previous|prior)\s+)"
    ),
}


def extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            parts: list[str] = []
            for name in ("word/document.xml", "word/header1.xml", "word/footer1.xml"):
                if name not in zf.namelist():
                    continue
                tree = ET.fromstring(zf.read(name))
                for t in tree.iter(f"{{{_NS['w']}}}t"):
                    if t.text:
                        parts.append(t.text)
            return " ".join(parts)
    except (zipfile.BadZipFile, ET.ParseError, KeyError):
        return ""


def extract_text_from_base64(b64: str) -> str:
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception:
        return ""
    if data[:4] == b"PK\x03\x04":
        return extract_docx_text(data)
    try:
        return data.decode("utf-8", errors="ignore")
    except Exception:
        return ""


class Scanner:
    def __init__(self, rule_names: tuple[str, ...]) -> None:
        self._rules = {
            name: pattern for name, pattern in BUILTIN_RULES.items() if name in rule_names
        }

    def scan_text(self, text: str, field_name: str) -> ScanResult:
        result = ScanResult()
        for rule_name, pattern in self._rules.items():
            for m in pattern.finditer(text):
                result.matches.append(
                    ScanMatch(
                        rule=rule_name,
                        field=field_name,
                        start=m.start(),
                        end=m.end(),
                        matched=m.group(),
                    )
                )
        return result

    def mask_text(self, text: str, matches: list[ScanMatch]) -> str:
        if not matches:
            return text
        sorted_matches = sorted(matches, key=lambda m: m.start, reverse=True)
        for m in sorted_matches:
            text = text[: m.start] + "[REDACTED]" + text[m.end :]
        return text
