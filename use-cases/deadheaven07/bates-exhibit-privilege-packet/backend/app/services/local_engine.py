"""Local fallback intelligence engine (STRICTLY A FALLBACK).

This module is the demoted offline path that runs ONLY when the SuperDocs
platform is unavailable (see `SuperDocsUnavailableError`). The primary
intelligence layer is the SuperDocs async chat API with
`approval_mode: "ask_every_time"`; every proposal surfaces as a native
`pending_change` requiring human approval.

The regex engine here exists so the product remains usable during a
platform outage and so the offline evaluation suite can run without a
network or API key. It is intentionally simpler than the SuperDocs
semantic engine and is documented as such.
"""

import re
from pathlib import Path

from app.services.superdocs_port import (
    PIICategory,
    PIIDetectionResult,
    PIIEntity,
    PrivilegeAnalysisResult,
    PrivilegeCategory,
)

_PII_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("phone", re.compile(r"\(?\d{3}\)?[.\s-]?\d{3}[.\s-]?\d{4}(?![\d-])")),
    ("account_number", re.compile(r"\b[A-Z]{2,10}[- ]?\d{4}[- ]?\d{4}\b", re.IGNORECASE)),
    ("account_number", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b")),
    ("name", re.compile(r"(?i)(?:employee|name)\s*[:]\s*([A-Z][a-z]+ [A-Z][a-z]+)")),
]

# Terms that look like PII but are document furniture (invoice refs, dates,
# page markers, statement codes). The real SuperDocs engine is expected to
# reject these semantically; the fallback engine filters them by pattern.
_FALSE_POSITIVE_PATTERNS: list[re.Pattern] = [
    re.compile(r"\bFQ-\d{4}\b"),
    re.compile(r"\bINV-\d{3,}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bPage\b", re.IGNORECASE),
]

_PRIVILEGE_KEYWORDS: list[tuple[PrivilegeCategory, str]] = [
    (PrivilegeCategory.ATTORNEY_CLIENT, "attorney client privileged"),
    (PrivilegeCategory.ATTORNEY_CLIENT, "confidential attorney client"),
    (PrivilegeCategory.ATTORNEY_CLIENT, "legal advice from counsel"),
    (PrivilegeCategory.WORK_PRODUCT, "work product"),
    (PrivilegeCategory.WORK_PRODUCT, "prepared in anticipation of litigation"),
    (PrivilegeCategory.JOINT_DEFENSE, "joint defense"),
    (PrivilegeCategory.COMMON_INTEREST, "common interest"),
]


class LocalPIIFallbackEngine:
    """Deterministic regex-based PII detector over extracted PDF text.

    Mirrors the shape of `SuperDocsPort.detect_pii` so it can stand in
    wherever the platform is unreachable.
    """

    def __init__(
        self,
        pii_patterns: list[tuple[str, re.Pattern]] | None = None,
        false_positive_patterns: list[re.Pattern] | None = None,
    ):
        self.pii_patterns = pii_patterns or _PII_PATTERNS
        self.false_positive_patterns = false_positive_patterns or _FALSE_POSITIVE_PATTERNS

    def detect_pii(
        self,
        source: Path | bytes,
        categories: list[PIICategory] | None = None,
        session_id: str = "",
        document_id: str = "",
        change_id_prefix: str = "local-",
    ) -> PIIDetectionResult:
        pages = _extract_pages(source)
        entities: list[PIIEntity] = []

        for page_index, page_text in enumerate(pages):
            if not page_text:
                continue
            for category_value, pattern in self.pii_patterns:
                for match in pattern.finditer(page_text):
                    if any(fp.search(match.group(0)) for fp in self.false_positive_patterns):
                        continue
                    category = PIICategory(category_value)
                    if categories and category not in categories:
                        continue
                    text = (
                        match.group(1).strip()
                        if category_value == "name"
                        else match.group(0).strip()
                    )
                    start = match.start()
                    entities.append(
                        PIIEntity(
                            category=category,
                            text=text,
                            page_number=page_index + 1,
                            start_offset=start,
                            end_offset=match.end(),
                            confidence=0.95,
                            context_before=page_text[max(0, start - 40) : start],
                            context_after=page_text[match.end() : match.end() + 40],
                            change_id=f"{change_id_prefix}{page_index + 1}-{len(entities) + 1}",
                        )
                    )

        seen: set[tuple] = set()
        unique: list[PIIEntity] = []
        for entity in entities:
            key = (entity.category, entity.text, entity.page_number)
            if key not in seen:
                seen.add(key)
                unique.append(entity)

        return PIIDetectionResult(
            entities=unique,
            total_count=len(unique),
            session_id=session_id,
            document_id=document_id,
        )


class LocalPrivilegeFallbackEngine:
    """Keyword-based privilege classification fallback.

    Deliberately conservative: only flags clearly privileged language and
    leaves everything else NOT_PRIVILEGED so a human reviewer always decides.
    """

    def analyze(
        self,
        source: Path | bytes,
        session_id: str = "",
        document_id: str = "",
    ) -> PrivilegeAnalysisResult:
        text = _extract_text(source).lower()
        matched: list[tuple[PrivilegeCategory, str]] = []
        for category, phrase in _PRIVILEGE_KEYWORDS:
            if phrase in text:
                matched.append((category, phrase))

        if not matched:
            return PrivilegeAnalysisResult(
                is_privileged=False,
                category=None,
                reason="No privileged language detected by fallback engine",
                confidence=0.0,
                key_phrases=[],
            )

        category = matched[0][0]
        confidence = min(0.95, 0.6 + 0.05 * len(matched))
        return PrivilegeAnalysisResult(
            is_privileged=True,
            category=category,
            reason=f"Privileged language matched: {', '.join(p for _, p in matched)}",
            confidence=confidence,
            key_phrases=[p for _, p in matched],
        )


def _extract_pages(source: Path | bytes) -> list[str]:
    import fitz

    if isinstance(source, bytes):
        doc = fitz.open(stream=source, filetype="pdf")
    else:
        doc = fitz.open(source)
    try:
        return ["".join(page.get_text()) for page in doc]
    finally:
        doc.close()


def _extract_text(source: Path | bytes) -> str:
    return "\n".join(_extract_pages(source))
