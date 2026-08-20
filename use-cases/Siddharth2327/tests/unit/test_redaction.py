import zipfile
from pathlib import Path

import pytest

from winloss_superdocs.redaction import (
    RedactionBlockedExport,
    build_redacted_context,
    extract_text_from_file,
    redact_text,
    scan_for_leaks,
)


def test_redact_text_replaces_known_name():
    out = redact_text("Acme Robotics Inc. loved the demo.", ["Acme Robotics Inc."])
    assert "Acme Robotics Inc." not in out
    assert "[CUSTOMER]" in out


def test_redact_text_case_insensitive_and_aliases():
    out = redact_text("acme robotics called it 'Acme' internally.", ["Acme Robotics Inc.", "Acme"])
    assert "acme" not in out.lower()


def test_build_redacted_context_never_includes_customer_name():
    records = [
        {
            "deal_code": "DEAL-1",
            "outcome": "win",
            "segment": "Mid-Market",
            "competitors": ["Comp Corp"],
            "customer_name": "Acme Robotics Inc.",
            "customer_aliases": ["Acme"],
            "evidence_snippets": ["Acme Robotics Inc. said the demo sealed it."],
        }
    ]
    refs = build_redacted_context(records)
    assert len(refs) == 1
    ref = refs[0]
    # The customer name must not appear anywhere in the object sent to the AI.
    assert "Acme" not in ref.deal_code
    assert all("acme" not in s.lower() for s in ref.evidence_snippets)
    assert "[CUSTOMER]" in ref.evidence_snippets[0]
    # DebriefRef has no customer_name field at all -- structurally cannot leak.
    assert not hasattr(ref, "customer_name")


def test_scan_for_leaks_clean():
    result = scan_for_leaks("A brief about Comp Corp and Mid-Market patterns.", ["Acme Robotics Inc."])
    assert result.ok


def test_scan_for_leaks_detects_adversarial_smuggled_name():
    """A quote copied verbatim from a transcript could smuggle a customer name into
    the brief even if the orchestration code never intentionally included it -- this
    is exactly the failure mode the post-hoc scan exists to catch."""
    leaked_html = "<p>One customer, Acme Robotics Inc., praised the throughput.</p>"
    result = scan_for_leaks(leaked_html, ["Acme Robotics Inc."])
    assert not result.ok
    assert "Acme Robotics Inc." in result.leaked_terms


def test_scan_for_leaks_html_text_extraction():
    html = "<div><h2>Wording</h2><p>Great quote from Beta Systems LLC here.</p></div>"
    result = scan_for_leaks(html, ["Beta Systems LLC"])
    assert not result.ok


def test_raise_if_leaked_blocks_export():
    result = scan_for_leaks("mentions Gamma Health Group", ["Gamma Health Group"])
    with pytest.raises(RedactionBlockedExport):
        result.raise_if_leaked("Quarterly Brief 2025Q4")


def test_short_terms_ignored_to_avoid_false_positives():
    # A 2-character "customer name" (e.g. a bad data entry) must not block every
    # export that happens to contain that substring.
    result = scan_for_leaks("this text contains the word 'it' constantly", ["It"])
    assert result.ok


def test_extract_text_from_docx(tmp_path):
    docx_path = tmp_path / "fake.docx"
    with zipfile.ZipFile(docx_path, "w") as z:
        z.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:r><w:t>Mentions Acme Robotics Inc. here</w:t>"
            "</w:r></w:p></w:body></w:document>",
        )
    text = extract_text_from_file(docx_path)
    assert "Acme Robotics Inc." in text


def test_extract_text_from_txt(tmp_path):
    f = tmp_path / "plain.txt"
    f.write_text("hello world")
    assert extract_text_from_file(f) == "hello world"


def test_extract_text_unsupported_format_raises(tmp_path):
    f = tmp_path / "brief.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    with pytest.raises(ValueError, match="does not support"):
        extract_text_from_file(f)
