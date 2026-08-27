from datetime import datetime, timezone

from agents import DiffProposal, ProposedChange, DocumentState, MathCheckAgent, SpellingFixAgent
from schema import ReviewState


class FakeDiffModel:
    def __init__(self, proposal: DiffProposal) -> None:
        self.proposal = proposal
        self.calls: list[dict] = []

    def propose(self, *, action: str, sections: dict[str, str], restrictions: list[str]) -> DiffProposal:
        self.calls.append(
            {"action": action, "sections": sections, "restrictions": restrictions})
        return self.proposal


def envelope(*, assigned_to: str, action: str, target: str, state: str) -> dict:
    return {
        "document_id": "invoice-2026",
        "assigned_to": assigned_to,
        "scope": {"action": action, "target_sections": [target]},
        "review_state": state,
        "issued_by": "orchestrator",
        "issued_at": datetime(2026, 8, 24, tzinfo=timezone.utc),
    }


def test_spelling_agent_uses_injected_structured_llm_diff() -> None:
    model = FakeDiffModel(DiffProposal(changes=[ProposedChange(
        section="narrative",
        before="Payment recived.",
        after="Payment received.",
    )]))
    document = DocumentState("invoice-2026", ReviewState.DRAFT, {
        "narrative": "Payment recived.", "pricing_table": "1 x 10 = 10\nTotal: 10"
    })

    result = SpellingFixAgent(model).process(
        envelope(assigned_to="spelling-agent", action="fix spelling",
                 target="narrative", state="draft"),
        document,
        {},
    )

    assert result.changed_sections["narrative"] == (
        "Payment recived.", "Payment received.")
    assert model.calls[0]["action"] == "fix spelling"


def test_math_agent_uses_injected_structured_llm_diff() -> None:
    model = FakeDiffModel(DiffProposal(changes=[ProposedChange(
        section="pricing_table",
        before="1 x 10 = 10\nTotal: 10",
        after="1 x 10 = 10\nTotal: 10",
    )]))
    document = DocumentState("invoice-2026", ReviewState.PENDING_REVIEW, {
        "narrative": "Payment received.", "pricing_table": "1 x 10 = 10\nTotal: 10"
    })

    result = MathCheckAgent(model).process(
        envelope(assigned_to="math-check-agent", action="verify totals",
                 target="pricing_table", state="pending_review"),
        document,
    )

    assert result.changed_sections == {}
    assert model.calls[0]["sections"] == {
        "pricing_table": "1 x 10 = 10\nTotal: 10"}
