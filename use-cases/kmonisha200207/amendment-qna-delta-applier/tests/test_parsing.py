from pathlib import Path

from delta_applier.parsing import parse_amendment, parse_qna, parse_solicitation

FIXTURES = Path(__file__).parent.parent / "fixtures"


def test_parse_solicitation_extracts_baseline_facts():
    text = (FIXTURES / "solicitation.txt").read_text(encoding="utf-8")
    facts = parse_solicitation(text)
    by_key = {(f.rule_type, f.key): f for f in facts}

    assert by_key[("page_limit", "volume_I")].value == 40
    assert by_key[("due_date", "proposal_due")].value == "2026-09-15 17:00 ET"
    assert by_key[("eval_weight", "Technical Approach")].value == 40
    assert by_key[("eval_weight", "Price")].value == 30
    assert by_key[("requirement", "C.2")].value.startswith("provide a disaster recovery")
    assert by_key[("staffing", "helpdesk")].value.startswith("maintain a helpdesk")
    assert all(f.change_kind == "baseline" for f in facts)


def test_parse_amendment_extracts_deltas():
    text = (FIXTURES / "amendment_0001.txt").read_text(encoding="utf-8")
    facts = parse_amendment(text, "amendment_0001.txt")
    by_key = {(f.rule_type, f.key): f for f in facts}

    assert by_key[("page_limit", "volume_I")].value == 25
    assert by_key[("page_limit", "volume_I")].change_kind == "modified"
    assert by_key[("due_date", "proposal_due")].value == "2026-09-29 17:00 ET"
    assert by_key[("eval_weight", "Technical Approach")].value == 50
    assert by_key[("eval_weight", "Price")].value == 20
    assert by_key[("requirement", "C.4")].change_kind == "added"
    assert by_key[("requirement", "C.2")].change_kind == "deleted"
    assert by_key[("requirement", "C.2")].value is None

    # every fact must carry a citation back to its PARA
    for f in facts:
        assert f.source.document == "amendment_0001.txt"
        assert f.source.paragraph_id.startswith("PARA ")
        assert f.source.paragraph_text  # non-empty


def test_parse_qna_extracts_clarification_and_confirmations():
    text = (FIXTURES / "qna_0001.txt").read_text(encoding="utf-8")
    facts = parse_qna(text, "qna_0001.txt")
    by_key = {(f.rule_type, f.key): f for f in facts}

    assert by_key[("exec_summary_page_limit", "volume_I")].value == 2
    assert by_key[("exec_summary_page_limit", "volume_I")].change_kind == "clarified"

    assert by_key[("staffing", "helpdesk")].change_kind == "confirmed_no_change"
    assert by_key[("submission_method", "default")].change_kind == "confirmed_no_change"
