import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from analyze_structure import analyze, diff_reports, residue_notes, validate_export_artifact  # noqa: E402

MESSY_DOC = """
<html>
<body>
<h1>Vendor Policy</h1>
<h3>Payment Terms</h3>
<p>- Net 30 for all invoices</p>
<p>- Late fees apply after 30 days</p>
<table>
<tr><td>Item</td><td>Price</td></tr>
<tr><td>Widget</td><td>$5</td></tr>
</table>
<a href="/terms">click here</a>
<a href="/policy"></a>
<img src="logo.png">
</body>
</html>
"""

CLEAN_DOC = """
<html lang="en">
<body>
<h1>Vendor Policy</h1>
<h2>Payment Terms</h2>
<ul>
<li>Net 30 for all invoices</li>
<li>Late fees apply after 30 days</li>
</ul>
<table>
<tr><th scope="col">Item</th><th scope="col">Price</th></tr>
<tr><td>Widget</td><td>$5</td></tr>
</table>
<a href="/terms">Read the full payment terms</a>
<a href="/policy">View our late fee policy</a>
<img src="logo.png" alt="Company logo">
</body>
</html>
"""


def test_detects_skipped_heading_level():
    report = analyze(MESSY_DOC)
    assert len(report.heading_issues) >= 1
    assert any("h1 to h3" in i.reason for i in report.heading_issues)


def test_clean_doc_has_no_heading_issues():
    report = analyze(CLEAN_DOC)
    assert report.heading_issues == []


def test_detects_manual_bullets():
    report = analyze(MESSY_DOC)
    assert report.manual_bullet_paragraphs == 2


def test_real_list_not_flagged_as_manual_bullets():
    report = analyze(CLEAN_DOC)
    assert report.manual_bullet_paragraphs == 0
    assert report.real_list_count == 1


def test_detects_table_missing_headers():
    report = analyze(MESSY_DOC)
    assert len(report.table_issues) == 1
    assert "th" in report.table_issues[0].reason.lower()


def test_clean_table_has_scoped_headers():
    report = analyze(CLEAN_DOC)
    assert report.table_issues == []


def test_detects_generic_and_empty_link_text():
    report = analyze(MESSY_DOC)
    assert len(report.link_issues) == 2
    reasons = {i.reason for i in report.link_issues}
    assert any("generic" in r for r in reasons)
    assert any("empty" in r for r in reasons)


def test_detects_missing_alt_text():
    report = analyze(MESSY_DOC)
    assert len(report.image_issues) == 1
    assert report.image_issues[0].src == "logo.png"


def test_detects_missing_lang_attribute():
    assert analyze(MESSY_DOC).has_lang_attribute is False
    assert analyze(CLEAN_DOC).has_lang_attribute is True


def test_diff_report_shows_real_improvement():
    before = analyze(MESSY_DOC)
    after = analyze(CLEAN_DOC)
    diff = diff_reports(before, after)
    assert diff["total_issues"]["before"] > diff["total_issues"]["after"]
    assert diff["total_issues"]["after"] == 0
    assert diff["heading_issues"] == {"before": 1, "after": 0}
    assert diff["image_issues"] == {"before": 1, "after": 0}


def test_residue_notes_empty_for_fully_clean_doc():
    assert residue_notes(analyze(CLEAN_DOC)) == []


def test_residue_notes_specific_not_generic():
    notes = residue_notes(analyze(MESSY_DOC))
    assert len(notes) > 0
    generic_phrases = {"some issues may remain", "please review manually", "check for accessibility issues"}
    for note in notes:
        lowered = note.lower()
        assert lowered not in generic_phrases, f"note is a generic disclaimer: {note!r}"
        assert len(note) > 40, f"note too short to be specific: {note!r}"
        assert " because" in lowered or "needs a human" in lowered or any(c.isdigit() for c in note), (
            f"note doesn't explain the specific reason: {note!r}"
        )


def test_invalid_export_artifact_is_reported(tmp_path):
    path = tmp_path / "output.pdf"
    path.write_bytes(b"not a pdf")
    result = validate_export_artifact(path, "pdf")
    assert result["valid"] is False


def test_valid_docx_container_is_reported(tmp_path):
    import zipfile

    path = tmp_path / "output.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "content")
        archive.writestr("word/document.xml", "document")
    assert validate_export_artifact(path, "docx")["valid"] is True