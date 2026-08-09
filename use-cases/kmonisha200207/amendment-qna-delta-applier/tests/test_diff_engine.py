from delta_applier.diff_engine import apply_batch, build_baseline_state
from delta_applier.models import ParsedFact, SourceRef


def _src(doc="doc.txt", para="PARA 1", text="some text"):
    return SourceRef(document=doc, paragraph_id=para, paragraph_text=text)


def test_apply_batch_produces_delta_for_changed_value():
    state = build_baseline_state(
        [ParsedFact("page_limit", "volume_I", 40, "baseline", _src("solicitation.txt", "L.3.2", "40 pages"))]
    )
    result = apply_batch(
        state, [ParsedFact("page_limit", "volume_I", 25, "modified", _src("amendment_0001.txt", "PARA 1", "25 pages"))]
    )

    assert len(result.deltas) == 1
    delta = result.deltas[0]
    assert delta.old_value == 40
    assert delta.new_value == 25
    assert state[("page_limit", "volume_I")].value == 25  # state advances


def test_apply_batch_is_idempotent_for_restated_value():
    state = build_baseline_state([ParsedFact("due_date", "proposal_due", "2026-09-15", "baseline", _src())])
    result = apply_batch(state, [ParsedFact("due_date", "proposal_due", "2026-09-15", "modified", _src())])
    assert result.deltas == []


def test_confirmed_no_change_matching_state_produces_confirmation_not_delta():
    state = build_baseline_state([ParsedFact("staffing", "helpdesk", "0600-1800", "baseline", _src())])
    result = apply_batch(
        state, [ParsedFact("staffing", "helpdesk", "0600-1800", "confirmed_no_change", _src("qna_0001.txt"))]
    )
    assert result.deltas == []
    assert len(result.confirmations) == 1


def test_confirmed_no_change_contradicting_state_is_surfaced_as_conflict_not_silently_resolved():
    state = build_baseline_state(
        [ParsedFact("staffing", "helpdesk", "0600-1800", "baseline", _src("amendment_0001.txt", "PARA 9", "changed to 24/7"))]
    )
    # amendment_0001 already changed staffing to 24/7 in `state`; a later Q&A
    # wrongly claims it's unchanged from the ORIGINAL solicitation value.
    result = apply_batch(
        state,
        [ParsedFact("staffing", "helpdesk", "original-0600-1800-value", "confirmed_no_change", _src("qna_0001.txt", "PARA 2", "unchanged"))],
    )
    assert result.deltas == []
    assert len(result.conflicts) == 1
    conflict = result.conflicts[0]
    assert conflict.existing_value == "0600-1800"
    assert conflict.new_value == "original-0600-1800-value"
    # state must NOT be silently overwritten by the conflicting claim
    assert state[("staffing", "helpdesk")].value == "0600-1800"


def test_new_key_with_no_baseline_is_an_added_delta():
    state = build_baseline_state([])
    result = apply_batch(state, [ParsedFact("requirement", "C.4", "new text", "added", _src("amendment_0001.txt", "PARA 4", "adds C.4"))])
    assert len(result.deltas) == 1
    assert result.deltas[0].old_value is None
    assert result.deltas[0].change_kind == "added"
