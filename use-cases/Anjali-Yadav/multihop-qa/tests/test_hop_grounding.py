import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.local_retrieval import chunk_documents, hybrid_search  # noqa: E402
from common.verification import quote_grounded  # noqa: E402
from common.test_imports import load_local_module  # noqa: E402

BUILD_ROOT = Path(__file__).resolve().parents[1]
_schemas = load_local_module(
    "multihop_qa_schemas",
    BUILD_ROOT / "schemas.py",
    dependencies={"schemas": BUILD_ROOT / "schemas.py"},
)
_main = load_local_module(
    "multihop_qa_main",
    BUILD_ROOT / "main.py",
    dependencies={"schemas": BUILD_ROOT / "schemas.py"},
)
answer_question = _main.answer_question
Hop = _schemas.Hop
MultiHopAnswer = _schemas.MultiHopAnswer


DOCUMENTS = {
    "doc_a": "Payment terms are net 30 days. Late fees apply after 30 days.",
    "doc_b": "Orders ship in 5 business days.",
    "doc_c": "The warranty lasts for 12 months.",
}


def test_hop_grounding_checks_specific_document_only():
    assert quote_grounded("net 30 days", DOCUMENTS["doc_a"]) is True
    assert quote_grounded("net 30 days", DOCUMENTS["doc_b"]) is False


def test_hops_are_deduplicated_by_document_and_quote():
    hops = [
        Hop(claim="Payment terms are net 30 days.", source_doc_id="doc_a", evidence_quote="net 30 days"),
        Hop(claim="Payment terms are net 30 days.", source_doc_id="doc_a", evidence_quote="net 30 days"),
        Hop(claim="Payment terms are net 30 days.", source_doc_id="doc_b", evidence_quote="ship in 5 business days"),
    ]

    deduped = MultiHopAnswer.dedupe_hops(hops)
    assert len(deduped) == 2


def test_answer_flags_when_no_supported_hops_exist():
    answer = MultiHopAnswer(answer=None, could_not_answer=True, hops=[])
    validated = answer.validate_against_documents(DOCUMENTS)
    assert validated.could_not_answer is True
    assert validated.answer is None


def test_empty_document_set_returns_no_answer():
    result = answer_question("What is the renewal term?", {})

    assert result.answer is None
    assert result.could_not_answer is True
    assert result.hops == []


def test_local_retrieval_prefers_relevant_chunk():
    chunks = chunk_documents([
        {"doc_id": "doc_a", "text": "Late fees apply after 30 days."},
        {"doc_id": "doc_b", "text": "Shipping takes 5 business days."},
    ])

    results = hybrid_search("late fees", chunks, top_k=2)
    assert results[0].doc_id == "doc_a"


def test_session_workflow_uploads_all_sources_and_exports_report(tmp_path):
    class Client:
        def __init__(self):
            self.uploads = []
            self.exports = []

        def upload(self, filename, text, session_id):
            self.uploads.append((filename, text, session_id))

        def export(self, session_id, fmt, out_path):
            self.exports.append((session_id, fmt, out_path))

    client = Client()
    report = _main.run_session_workflow(
        "Where are payment and shipping terms?",
        {"contract": DOCUMENTS["doc_a"], "orders": DOCUMENTS["doc_b"]},
        client,
        str(tmp_path / "nested" / "answer.json"),
        session_id="session-1",
    )

    assert len(client.uploads) == 2
    assert report["session_id"] == "session-1"
    assert report["hops"]
    assert client.exports[0][1] == "markdown"
    assert (tmp_path / "nested" / "answer.json").is_file()
    assert "contract" in (tmp_path / "nested" / "answer.md").read_text()
