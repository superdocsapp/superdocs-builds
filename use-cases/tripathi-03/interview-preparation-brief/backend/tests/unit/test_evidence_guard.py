from app.agents.contracts import NO_EVIDENCE, ResumeParserInput
from app.agents.nodes.resume_parser import ResumeParser
from app.utils.evidence_guard import enforce_evidence_or_fallback
import pytest


def test_no_evidence_constant():
    assert NO_EVIDENCE == "No evidence found."


def test_fallback_when_no_evidence(monkeypatch):
    from app.core import config

    monkeypatch.setenv("EVIDENCE_FALLBACK", "No evidence found.")
    config.get_settings.cache_clear()
    answer, has = enforce_evidence_or_fallback("Invented answer", [])
    assert has is False
    assert answer == "No evidence found."
    config.get_settings.cache_clear()


def test_keeps_answer_when_evidence_present():
    answer, has = enforce_evidence_or_fallback(
        "Led migration to Postgres",
        ["Led migration to Postgres at Acme"],
    )
    assert has is True
    assert "Postgres" in answer


def test_resume_parser_input_validation_rejects_empty():
    with pytest.raises(Exception):
        ResumeParserInput(session_id="abc", resume_text="   ")


@pytest.mark.asyncio
async def test_resume_parser_node_normalizes_and_merges_state():
    node = ResumeParser()
    state = {
        "session_id": "11111111-1111-1111-1111-111111111111",
        "resume_text": "Jane Doe\n\n\nBuilt APIs   with FastAPI",
    }
    updated = await node(state)
    assert updated["current_step"] == "ResumeParser"
    assert updated["resume_char_count"] > 0
    assert "FastAPI" in updated["resume_normalized"]
    assert "\n\n\n" not in updated["resume_normalized"]
