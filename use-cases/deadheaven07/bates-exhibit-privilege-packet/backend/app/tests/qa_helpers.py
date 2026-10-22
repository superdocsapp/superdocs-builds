"""Shared QA helpers for API-level tests and final-artifact PII verification."""

import hashlib
import json
import re
from pathlib import Path

import fitz

PII_FIXTURES = {
    "ssn": ["123-45-6789", "987-65-4321"],
    "email": ["jane.public@example.com"],
    "phone": ["(212) 555-0199"],
    "name": ["Jane Smith", "John Doe"],
    "account_numeric": ["8821-4433-2211-9900"],
    "account_alphanumeric": ["ACC-8821-4433"],
}


def make_pdf(lines, page_count=1, page_size=(612, 792)):
    doc = fitz.open()
    for _ in range(page_count):
        page = doc.new_page(width=page_size[0], height=page_size[1])
        for j, line in enumerate(lines):
            page.insert_text((72, 100 + j * 20), line, fontsize=12, fontname="helv")
    data = doc.tobytes()
    doc.close()
    return data


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pdf_text(path: Path) -> str:
    doc = fitz.open(path)
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


def assert_text_free_of(text: str, forbidden_values, label: str) -> None:
    lowered = text.lower()
    for values in forbidden_values.values():
        for value in values:
            assert value.lower() not in lowered, f"Forbidden value {value!r} found in {label}"


def assert_pdf_free_of(path: Path, forbidden_values, label: str = "artifact") -> None:
    assert_text_free_of(pdf_text(path), forbidden_values, f"{label} {path}")


def assert_artifacts_pii_free(final_dir, forbidden_values) -> None:
    """Scan final_packet.pdf, exhibit_index.pdf, privilege_log.pdf, cover pages
    and every exhibit PDF inside a built packet directory."""
    final_dir = Path(final_dir)
    final_packet = final_dir / "final_packet.pdf"
    assert final_packet.exists(), "final_packet.pdf missing"
    assert_pdf_free_of(final_packet, forbidden_values, "final_packet.pdf")

    index = final_dir / "exhibit_index.pdf"
    if index.exists():
        assert_pdf_free_of(index, forbidden_values, "exhibit_index.pdf")

    log = final_dir / "privilege_log.pdf"
    if log.exists():
        assert_pdf_free_of(log, forbidden_values, "privilege_log.pdf")

    exhibits_dir = final_dir / "exhibits"
    if exhibits_dir.exists():
        for exhibit in sorted(exhibits_dir.glob("EX-*.pdf")):
            assert_pdf_free_of(exhibit, forbidden_values, exhibit.name)

    manifest = final_dir / "manifest.json"
    if manifest.exists():
        data = json.loads(manifest.read_text())
        lowered = json.dumps(data, default=str).lower()
        for values in forbidden_values.values():
            for value in values:
                assert value.lower() not in lowered, (
                    f"Forbidden value {value!r} found in manifest.json"
                )


_PII_PATTERNS = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")),
    ("phone", re.compile(r"\(?\d{3}\)?[.\s-]?\d{3}[.\s-]?\d{4}(?![\d-])")),
    ("account_number", re.compile(r"\b[A-Z]{2,10}[- ]?\d{4}[- ]?\d{4}\b", re.IGNORECASE)),
    ("account_number", re.compile(r"\b\d{4}-\d{4}-\d{4}-\d{4}\b")),
    ("name", re.compile(r"(?i)(?:employee|name)\s*[:]\s*([A-Z][a-z]+ [A-Z][a-z]+)")),
]

_FALSE_POSITIVE_PATTERNS = [
    re.compile(r"\bFQ-\d{4}\b"),
    re.compile(r"\bINV-\d{3,}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\bPage\b", re.IGNORECASE),
]


class FakeSuperDocsService:
    """In-memory stand-in for the SuperDocs intelligence engine.

    Mirrors the SuperDocs API contract at the integration-service level so API
    and service tests exercise the SuperDocs-native code paths without a
    network dependency. Detection is performed on the locally stored original
    PDF with the same pattern families the real engine is expected to return.
    """

    def __init__(self):
        from app.config import get_settings
        from app.services.superdocs_port import JobStatus

        self._settings = get_settings()
        self.JobStatus = JobStatus
        self.detect_calls = 0
        self.apply_calls = 0

    async def upload_document_to_superdocs(self, session, document):
        from app.services.superdocs_port import DocumentUploadResult

        document.superdocs_session_id = "fake-session"
        document.superdocs_document_id = "fake-doc"
        await session.commit()
        return DocumentUploadResult(
            session_id="fake-session",
            document_id="fake-doc",
            chunks_count=0,
            version_id="v1",
            page_setup={},
            html=None,
        )

    async def detect_pii(self, session, document, categories=None, siblings=None):
        from app.domain.document import DocumentType
        from app.services.superdocs_port import PIICategory, PIIDetectionResult, PIIEntity

        self.detect_calls += 1
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        entities = []
        if document.document_type not in (DocumentType.PDF, DocumentType.SCANNED_PDF):
            return PIIDetectionResult(
                entities=[],
                total_count=0,
                session_id=document.superdocs_session_id or "fake-session",
                document_id=document.superdocs_document_id or "fake-doc",
            )

        from app.services.storage import original_path_for

        path = original_path_for(document)
        if not path.exists():
            return PIIDetectionResult(
                entities=[],
                total_count=0,
                session_id=document.superdocs_session_id or "fake-session",
                document_id=document.superdocs_document_id or "fake-doc",
            )

        doc = fitz.open(path)
        try:
            for page_index, page in enumerate(doc):
                page_text = page.get_text()
                if not page_text:
                    continue
                for category_value, pattern in _PII_PATTERNS:
                    for match in pattern.finditer(page_text):
                        if any(fp.search(match.group(0)) for fp in _FALSE_POSITIVE_PATTERNS):
                            continue
                        category = PIICategory(category_value)
                        if categories and category not in categories:
                            continue
                        raw_text = match.group(0).strip()
                        text = raw_text
                        if category_value == "name":
                            text = match.group(1).strip()
                        elif category_value == "account_number" and any(
                            ch.isalpha() for ch in raw_text
                        ):
                            text = raw_text.upper()
                        if not text:
                            continue
                        rects = page.search_for(raw_text) or page.search_for(text)
                        x0 = y0 = x1 = y1 = None
                        if rects:
                            rect = rects[0]
                            x0, y0, x1, y1 = rect.x0, rect.y0, rect.x1, rect.y1
                        start = match.start()
                        before = page_text[max(0, start - 40) : start]
                        after = page_text[match.end() : match.end() + 40]
                        entities.append(
                            PIIEntity(
                                category=category,
                                text=text,
                                page_number=page_index + 1,
                                start_offset=start,
                                end_offset=match.end(),
                                confidence=0.95,
                                context_before=before,
                                context_after=after,
                                x0=x0,
                                y0=y0,
                                x1=x1,
                                y1=y1,
                            )
                        )
        finally:
            doc.close()

        seen = set()
        unique = []
        for entity in entities:
            key = (entity.category, entity.text, entity.page_number)
            if key not in seen:
                seen.add(key)
                unique.append(entity)

        return PIIDetectionResult(
            entities=unique,
            total_count=len(unique),
            session_id=document.superdocs_session_id or "fake-session",
            document_id=document.superdocs_document_id or "fake-doc",
        )

    async def apply_redactions(self, session, document, candidates):
        """Mirror of the SuperDocs apply sync. The authoritative byte-scrub is
        performed locally by the application layer; this fake only records the
        sync and returns a completed job status (no file mutation, so
        re-application stays deterministic and never clobbers the scrubbed
        artifact)."""
        self.apply_calls += 1
        if not document.superdocs_session_id:
            await self.upload_document_to_superdocs(session, document)
            await session.refresh(document)

        return self.JobStatus(
            job_id="fake-job",
            status="completed",
            result={"applied": sum(1 for c in candidates if c.approved)},
        )
