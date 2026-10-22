"""Unit-level regression tests for H-1: alphanumeric account number
detection. Exercises the redaction service detection against real PDFs with
generalized fixtures (no hardcoded production values).
"""

import pytest

from app.services.redaction import RedactionDetectionService
from qa_helpers import make_pdf


def _detect_lines(lines, page_count=1):
    pdf_bytes = make_pdf(lines, page_count=page_count)
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes)
        tmp.flush()
        service = RedactionDetectionService()
        results = service.detect_in_pdf(tmp.name)
    return results


def _account_matches(results):
    return [
        (r.matched_text, r.category.value, (r.x0, r.y0, r.x1, r.y1))
        for r in results
        if r.category.value == "account_number"
    ]


@pytest.mark.parametrize("line,expected_text", [
    ("Account: ACC-8821-4433", "ACC-8821-4433"),
    ("ACC-8821-4433", "ACC-8821-4433"),
    ("acc-8821-4433", "acc-8821-4433"),
    ("Account: ACC 8821 4433", "ACC 8821 4433"),
    ("Account number: ACCOUNT-8821-4433", "ACCOUNT-8821-4433"),
    ("ACCT 8821 4433", "ACCT 8821 4433"),
    ("ACC-8821-4433 is the client account", "ACC-8821-4433"),
])
def test_alphanumeric_account_patterns_detected(line, expected_text):
    matches = _account_matches(_detect_lines([line]))
    texts = [m[0] for m in matches]
    assert expected_text in texts, f"line={line!r} matches={texts}"


def test_alphanumeric_account_with_coordinates():
    results = _detect_lines(["Account: ACC-8821-4433"])
    match = next(r for r in results if r.category.value == "account_number")
    assert match.x0 >= 0 and match.y0 >= 0 and match.x1 > match.x0 and match.y1 > match.y0
    assert match.page_number == 1


@pytest.mark.parametrize("line", [
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
])
def test_non_accounts_not_detected(line):
    matches = _account_matches(_detect_lines([line]))
    assert matches == [], f"line={line!r} produced matches={matches}"


def test_privilege_markers_not_detected_as_names():
    results = _detect_lines(["CONFIDENTIAL ATTORNEY CLIENT PRIVILEGED", "Privileged Communication"])
    names = [r.matched_text for r in results if r.category.value == "name"]
    assert names == [], f"privilege markers flagged as names: {names}"


def test_pure_numeric_accounts_still_detected():
    results = _detect_lines(["Routing 8821-4433-2211-9900"])
    matches = _account_matches(results)
    assert any(m[0] == "8821-4433-2211-9900" for m in matches)


def test_multi_page_detection():
    import fitz
    import tempfile

    doc = fitz.open()
    doc.new_page()
    page_two = doc.new_page()
    page_two.insert_text((72, 100), "Account: ACC-8821-4433", fontsize=12, fontname="helv")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        doc.save(tmp.name)
        doc.close()
        service = RedactionDetectionService()
        results = service.detect_in_pdf(tmp.name)
    match = next(r for r in results if "ACC-8821-4433" in r.matched_text)
    assert match.page_number == 2, "account on page two must be attributed to page 2"


def test_no_false_positive_on_bates_stamps():
    results = _detect_lines(["Exhibit FQ-0500", "Bates: QA-1000", "Stamp QA-1001"])
    assert _account_matches(results) == []


def test_detect_is_deterministic():
    lines = ["Account: ACC-8821-4433", "SSN: 123-45-6789"]
    first = _account_matches(_detect_lines(lines))
    second = _account_matches(_detect_lines(lines))
    assert first == second