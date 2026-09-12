import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.test_imports import load_local_module  # noqa: E402

BUILD_ROOT = Path(__file__).resolve().parents[1]
_schemas = load_local_module(
    "citation_verifier_schemas",
    BUILD_ROOT / "schemas.py",
    dependencies={"schemas": BUILD_ROOT / "schemas.py"},
)
citation_main = load_local_module(
    "citation_verifier_main",
    BUILD_ROOT / "main.py",
    dependencies={"schemas": BUILD_ROOT / "schemas.py"},
)
build_report = citation_main.build_report
extract_citation_pairs = citation_main.extract_citation_pairs
verify_pairs = citation_main.verify_pairs
CitationPair = _schemas.CitationPair


class FakeClient:
    def __init__(self, verdict="yes", reason="Supported by the cited text."):
        self.verdict = verdict
        self.reason = reason

    def chat(self, **kwargs):
        return {"verdict": self.verdict, "reason": self.reason}


def test_extract_citation_pairs_from_inline_markers():
    text = "Late fees are due after 30 days.[1] Payment is net 30.[2]"
    refs = {
        "1": "Late fees apply after 30 days.",
        "2": "Invoices are payable in 30 days.",
    }

    pairs = extract_citation_pairs(text, refs)

    assert len(pairs) == 2
    assert pairs[0].claim == "Late fees are due after 30 days."
    assert pairs[0].citation_target == "1"


def test_extract_citation_pairs_supports_document_qualified_targets():
    pairs = extract_citation_pairs(
        "The term is defined here.[contract:A]",
        {"contract": {"A": "The term is 30 days."}},
    )

    assert pairs[0].source_doc_id == "contract"
    assert pairs[0].citation_target == "A"


def test_verify_pairs_marks_missing_reference_as_unverifiable():
    pairs = [
        CitationPair(
            claim="The vendor may charge a late fee.",
            citation_target="99",
            source_doc_id="contract",
        )
    ]

    result = verify_pairs(pairs, {"contract": "Late fees apply after 30 days."}, FakeClient())

    assert result[0]["verdict"] == "unverifiable"
    assert "not in the uploaded set" in result[0]["reason"].lower()
    assert result[0]["candidate_sources"]


def test_verify_pairs_uses_per_citation_findings_not_claim_level_summary():
    pairs = [
        CitationPair(claim="The service is available 24/7.", citation_target="A", source_doc_id="doc1"),
        CitationPair(claim="The service is available 24/7.", citation_target="B", source_doc_id="doc1"),
    ]

    references = {
        "doc1": {
            "A": "The service is available 24 hours a day, seven days a week.",
            "B": "The service is only available during business hours.",
        }
    }

    result = verify_pairs(pairs, references, FakeClient(verdict="yes", reason="Supported."))

    assert len(result) == 2
    assert all(item["verdict"] in {"yes", "no", "partial", "unverifiable"} for item in result)


def test_build_report_verifies_extracted_pairs_instead_of_only_echoing_them():
    report = build_report(
        "The service is available 24/7.[A]",
        {"A": "The service is available every day."},
        FakeClient(),
    )

    assert report["pairs"][0]["citation_target"] == "A"
    assert report["findings"][0]["verdict"] == "yes"


def test_build_report_preserves_unverifiable_finding():
    report = build_report(
        "The service is available 24/7.[99]",
        {"A": "The service is available every day."},
        FakeClient(),
    )

    assert report["findings"][0]["verdict"] == "unverifiable"


def test_cli_fails_cleanly_when_api_key_is_missing(monkeypatch):
    def missing_api_key():
        raise RuntimeError("SUPERDOCS_API_KEY is not configured")

    monkeypatch.setattr(citation_main, "get_required_api_key", missing_api_key)
    monkeypatch.setattr(sys, "argv", ["citation-verifier", "document.txt"])

    with pytest.raises(SystemExit) as raised:
        citation_main.main()

    assert raised.value.code == 2


def test_session_workflow_uploads_source_and_exports_report(tmp_path):
    class Client:
        def __init__(self):
            self.uploads = []
            self.exports = []

        def upload(self, filename, text, session_id):
            self.uploads.append((filename, text, session_id))

        def chat(self, session_id, message):
            return {"verdict": "yes", "reason": "The passage supports the claim."}

        def export(self, session_id, fmt, out_path):
            self.exports.append((session_id, fmt, out_path))

    client = Client()
    report = citation_main.run_session_workflow(
        "The service is available daily.[A]",
        {"A": "The service is available every day."},
        client,
        str(tmp_path / "nested" / "citations.json"),
        session_id="session-2",
    )

    assert len(client.uploads) == 1
    assert report["findings"][0]["verdict"] == "yes"
    assert client.exports[0][1] == "markdown"
    assert (tmp_path / "nested" / "citations.json").is_file()


def test_session_entailment_adapter_extracts_superdocs_response_text():
    class Client:
        def chat(self, session_id, message):
            return {"response": "VERDICT: partial\nReason: It supports the claim partly."}

    adapter = citation_main.SessionEntailmentClient(Client(), "session-4")

    result = adapter.chat(message="evaluate this citation")

    assert result.startswith("VERDICT: partial")


def test_session_workflow_marks_findings_unreviewed_by_default(tmp_path):
    class Client:
        def upload(self, filename, text, session_id):
            pass

        def chat(self, session_id, message):
            return {"verdict": "yes", "reason": "Supported."}

        def export(self, session_id, fmt, out_path):
            pass

    report = citation_main.run_session_workflow(
        "The term is 30 days.[A]",
        {"A": "The term is 30 days."},
        Client(),
        str(tmp_path / "report.json"),
    )

    assert report["findings"][0]["reviewed"] is False
    assert report["findings"][0]["accepted"] is None
