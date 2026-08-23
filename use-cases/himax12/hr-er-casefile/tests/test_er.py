from er_engine.issue import issue_letter, render_casefile
from er_engine.sequence import CaseFile, can_issue, outcome_summary, record_hearing_notes, record_meeting_notes
from er_engine.superdocs_flow import FakeDocs, parse_change_batch, parse_proposed_change_content


def _case() -> CaseFile:
    c = CaseFile(case_id="ER-100", employee_name="Jordan Hale", employee_id="E-44")
    c.open_case()
    return c


def test_refuse_invite_before_notes():
    c = _case()
    ok, why = can_issue(c, "invite_to_hearing")
    assert ok is False
    assert "meeting notes" in why.lower()
    assert "will not skip" in why.lower()


def test_pip_allowed_after_open():
    c = _case()
    docs = FakeDocs()
    out = issue_letter(c, "improvement_plan", docs)
    assert out["ok"] is True
    assert "performance improvement" in out["body"].lower()


def test_verbatim_in_outcome_never_paraphrased():
    c = _case()
    quote = "I was covering a sick colleague and the bus was cancelled."
    record_meeting_notes(c, "First meeting.", quote)
    docs = FakeDocs()
    issue_letter(c, "invite_to_hearing", docs)
    record_hearing_notes(c, "Hearing held.", quote)
    out = issue_letter(c, "outcome", docs)
    assert quote in out["body"]
    summary = outcome_summary(c)
    assert quote in summary
    assert "covering a sick colleague" in summary
    # Guardrail: we copy, we do not summarise.
    assert summary.count(quote) == 1


def test_second_parse_of_proposed_change_string():
    raw = {
        "changes": [
            {"change_id": "ch_1", "content": '{"html": "<p>ok</p>", "op": "edit"}'}
        ]
    }
    parsed = parse_change_batch(raw)
    assert parsed[0]["content"]["html"] == "<p>ok</p>"
    assert parse_proposed_change_content('{"a": 1}') == {"a": 1}


def test_sample_mode_stopping_rule():
    docs = FakeDocs()
    docs.sample_mode = True
    docs.upload("d", "x")
    docs.chat("d", "one")
    docs.chat("d", "two")
    docs.chat("d", "three")
    fourth = docs.chat("d", "four")
    assert fourth["status"] == "stopped"


def test_casefile_lists_letters():
    c = _case()
    docs = FakeDocs()
    issue_letter(c, "absence", docs)
    text = render_casefile(c)
    assert "ER-100" in text
    assert "absence" in text.lower()
