from datetime import datetime, timezone
from pathlib import Path

from agents import DocumentState
from orchestrator import Orchestrator
from schema import ReviewState


def test_orchestrator_runs_agent_a_to_agent_b_to_agent_a_and_logs_trace() -> None:
    document = DocumentState(
        "invoice-2026",
        ReviewState.DRAFT,
        {
            "narrative": "Payment recived within 30 days.",
            "pricing_table": "Widget: 2 x 25 = 50\nService: 3 x 20 = 60\nTotal: 100",
        },
    )
    initial_envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "restrictions": {"forbidden_sections": ["pricing_table"]},
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }
    log_path = Path("logs") / "test-orchestrator-trace.json"

    result = Orchestrator().run(
        document, initial_envelope, {
            "narrative": {"recived": "received"}}, log_path
    )

    assert [validation.accepted for validation in result.validations] == [
        True, True, True]
    assert result.accepted is True
    assert result.document.review_state is ReviewState.APPROVED
    assert result.document.sections["narrative"] == "Payment received within 30 days."
    assert result.document.sections["pricing_table"].endswith("Total: 110")
    assert [entry["received_by"] for entry in result.trace] == [
        "spelling-agent", "math-check-agent", "spelling-agent"
    ]
    log_text = log_path.read_text(encoding="utf-8")
    assert "recived" not in log_text
    assert "Payment received" not in log_text
    assert "Widget: 2 x 25" not in log_text
    log_path.unlink()


def test_orchestrator_can_start_from_a_fetch_only_adapter() -> None:
    document = DocumentState("invoice-2026", ReviewState.DRAFT, {
        "narrative": "Payment recived.",
        "pricing_table": "1 x 10 = 10\nTotal: 10",
    })

    class Fetcher:
        def fetch(self, document_id: str) -> DocumentState:
            assert document_id == "invoice-2026"
            return document

    envelope = {
        "document_id": "invoice-2026",
        "assigned_to": "spelling-agent",
        "scope": {"action": "fix spelling", "target_sections": ["narrative"]},
        "review_state": "draft",
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }
    result = Orchestrator().run_from_server(
        Fetcher(
        ), "invoice-2026", envelope, {"narrative": {"recived": "received"}}
    )

    assert result.accepted is True
    assert len(result.trace) == 3
