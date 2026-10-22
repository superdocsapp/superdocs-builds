"""Shared QA helpers for API-level tests and final-artifact PII verification."""

import hashlib
import json
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
    for i in range(page_count):
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
            assert value.lower() not in lowered, (
                f"Forbidden value {value!r} found in {label}"
            )


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