"""Regression tests for H-1: alphanumeric account number detection.

The detection engine now lives in SuperDocs; these tests drive the
SuperDocs-native detection path through the in-memory FakeSuperDocsService
against real PDFs with generalized fixtures (no hardcoded production values).
"""

import pytest
from qa_helpers import FakeSuperDocsService, make_pdf, sha256_of
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.document import Document, DocumentType, ProcessingStatus
from app.domain.packet import Packet
from app.services.redaction import RedactionDetectionService

settings = get_settings()


async def _detect_lines(test_session: AsyncSession, lines, page_count=1):
    pdf_bytes = make_pdf(lines, page_count=page_count)
    sha = sha256_of(pdf_bytes)
    original_path = settings.originals_path / f"{sha}.pdf"
    original_path.parent.mkdir(parents=True, exist_ok=True)
    original_path.write_bytes(pdf_bytes)

    packet = Packet(name="Account Detection Test")
    test_session.add(packet)
    await test_session.commit()
    await test_session.refresh(packet)

    doc = Document(
        packet_id=packet.id,
        display_order=1,
        original_filename="account_test.pdf",
        mime_type="application/pdf",
        file_size=len(pdf_bytes),
        sha256=sha,
        original_sha256=sha,
        processed_sha256=sha,
        document_type=DocumentType.PDF,
        page_count=page_count,
        processing_status=ProcessingStatus.COMPLETED,
    )
    test_session.add(doc)
    await test_session.commit()
    await test_session.refresh(doc)

    fake = FakeSuperDocsService()
    detection = RedactionDetectionService(superdocs=fake)
    pii_result = await detection.detect_pii_in_document(test_session, str(doc.id))

    candidates = await detection.create_redaction_candidates(test_session, str(doc.id), pii_result)
    return candidates, pii_result, sha


def _account_matches(candidates):
    return [
        (c.matched_text, c.category.value, (c.x0, c.y0, c.x1, c.y1))
        for c in candidates
        if c.category.value == "account_number"
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line,expected_text",
    [
        ("Account: ACC-8821-4433", "ACC-8821-4433"),
        ("ACC-8821-4433", "ACC-8821-4433"),
        ("acc-8821-4433", "ACC-8821-4433"),
        ("Account: ACC 8821 4433", "ACC 8821 4433"),
        ("Account number: ACCOUNT-8821-4433", "ACCOUNT-8821-4433"),
        ("ACCT 8821 4433", "ACCT 8821 4433"),
        ("ACC-8821-4433 is the client account", "ACC-8821-4433"),
    ],
)
async def test_alphanumeric_account_patterns_detected(
    test_session: AsyncSession, line, expected_text
):
    candidates, _, sha = await _detect_lines(test_session, [line])
    texts = [m[0] for m in _account_matches(candidates)]
    assert expected_text in texts, f"line={line!r} matches={texts}"


@pytest.mark.asyncio
async def test_alphanumeric_account_with_coordinates(test_session: AsyncSession):
    candidates, _, _ = await _detect_lines(test_session, ["Account: ACC-8821-4433"])
    match = next(c for c in candidates if c.category.value == "account_number")
    assert match.x0 >= 0 and match.y0 >= 0 and match.x1 > match.x0 and match.y1 > match.y0
    assert match.page_number == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "line",
    [
        "Ref: FQ-0500",
        "Invoice: INV-2026-001",
        "Date: 2026-08-14",
        "Page One",
        "Docket: 1:23-cv-04567",
        "Account is currently on hold",
        "ACC has no digits",
        "The account: 12345 only",
        "CONFIDENTIAL ATTORNEY CLIENT PRIVILEGED",
        "Attorney Client Privileged",
        "Privileged Communication",
        "Confidential Legal Advice",
    ],
)
async def test_non_accounts_not_detected(test_session: AsyncSession, line):
    candidates, _, _ = await _detect_lines(test_session, [line])
    assert _account_matches(candidates) == [], f"line={line!r} produced matches"


@pytest.mark.asyncio
async def test_privilege_markers_not_detected_as_names(test_session: AsyncSession):
    candidates, _, _ = await _detect_lines(
        test_session, ["CONFIDENTIAL ATTORNEY CLIENT PRIVILEGED", "Privileged Communication"]
    )
    names = [c.matched_text for c in candidates if c.category.value == "name"]
    assert names == [], f"privilege markers flagged as names: {names}"


@pytest.mark.asyncio
async def test_pure_numeric_accounts_still_detected(test_session: AsyncSession):
    candidates, _, _ = await _detect_lines(test_session, ["Routing 8821-4433-2211-9900"])
    matches = _account_matches(candidates)
    assert any(m[0] == "8821-4433-2211-9900" for m in matches)


@pytest.mark.asyncio
async def test_multi_page_detection(test_session: AsyncSession):
    candidates, _, _ = await _detect_lines(test_session, ["Account: ACC-8821-4433"], page_count=2)
    match = next(c for c in candidates if "ACC-8821-4433" in c.matched_text)
    assert match.page_number == 1 or match.page_number == 2
    assert match.page_number >= 1


@pytest.mark.asyncio
async def test_no_false_positive_on_bates_stamps(test_session: AsyncSession):
    candidates, _, _ = await _detect_lines(
        test_session, ["Exhibit FQ-0500", "Bates: QA-1000", "Stamp QA-1001"]
    )
    assert _account_matches(candidates) == []
