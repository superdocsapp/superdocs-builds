import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from common.test_imports import load_local_module  # noqa: E402

BUILD_ROOT = Path(__file__).resolve().parents[1]
diff_classifier = load_local_module(
    "version_diff_classifier",
    BUILD_ROOT / "diff_classifier.py",
)
version_diff_main = load_local_module(
    "version_diff_main",
    BUILD_ROOT / "main.py",
    dependencies={"diff_classifier": BUILD_ROOT / "diff_classifier.py"},
)
classify_diff = diff_classifier.classify_diff
summarize_changes = diff_classifier.summarize_changes
build_report = version_diff_main.build_report


def test_identical_documents_report_no_material_changes():
    before = "Payment terms apply net 30 days."
    after = "Payment terms apply net 30 days."

    report = summarize_changes(before, after)

    assert report["material_changes"] == []
    assert report["formatting_changes"] == 0
    assert report["has_material_change"] is False


def test_whitespace_and_heading_formatting_is_filtered_out():
    before = "Section 1\nPayment terms.\nNet 30."
    after = "Section 1\n  Payment terms.  \nNet 30."

    classification = classify_diff(before, after)

    assert classification["kind"] == "formatting"
    assert classification["substantive"] is False


def test_substantive_wording_change_is_flagged():
    before = "Late fees apply after 30 days."
    after = "Late fees apply after 45 days."

    classification = classify_diff(before, after)

    assert classification["kind"] == "substantive"
    assert classification["substantive"] is True
    assert classification["before_text"] == "Late fees apply after 30 days."
    assert classification["after_text"] == "Late fees apply after 45 days."


def test_cross_reference_renumbering_counts_as_substantive_even_if_small():
    before = "See Section 3.2 for definitions."
    after = "See Section 4.2 for definitions."

    classification = classify_diff(before, after)

    assert classification["kind"] == "substantive"
    assert classification["reason"] == "cross_reference_changed"


def test_summary_counts_formatting_and_material_diffs():
    before = "\nSection 1\nPayment terms.\nLate fees after 30 days.\n"
    after = "\nSection 1\nPayment terms.\nLate fees after 45 days.\n"

    report = summarize_changes(before, after)

    assert report["formatting_changes"] == 0
    assert len(report["material_changes"]) == 1
    assert report["has_material_change"] is True


def test_empty_documents_report_no_material_changes():
    report = summarize_changes("", "")

    assert report == {
        "material_changes": [],
        "formatting_changes": 0,
        "has_material_change": False,
    }


def test_build_report_exposes_the_same_deterministic_summary():
    report = build_report("Old payment terms.", "New payment terms.")

    assert report["has_material_change"] is True
    assert report["material_changes"][0]["reason"] == "wording_changed"


def test_session_workflow_uploads_versions_and_records_impact(tmp_path):
    class Client:
        def __init__(self):
            self.uploads = []
            self.exports = []

        def upload(self, filename, text, session_id):
            self.uploads.append((filename, text, session_id))

        def chat_with_review(self, session_id, message, approve_all):
            assert "who appears to benefit" in message
            return {"response": "The buyer benefits; push back on the longer term."}

        def export(self, session_id, fmt, out_path):
            self.exports.append((session_id, fmt, out_path))

    client = Client()
    report = version_diff_main.run_session_workflow(
        "Payment is due in 30 days.",
        "Payment is due in 45 days.",
        client,
        str(tmp_path / "nested" / "diff.json"),
        session_id="session-3",
    )

    assert [item[0] for item in client.uploads] == ["before.txt", "after.txt"]
    assert "push back" in report["impact_analysis"]
    assert client.exports[0][1] == "markdown"
    assert report["search_hits"]
    assert (tmp_path / "nested" / "diff.json").is_file()
