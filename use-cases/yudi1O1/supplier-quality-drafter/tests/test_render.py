from supplier_quality_drafter.models import ActionItem, DraftRequest, FailureMode
from supplier_quality_drafter.render import build_instruction, render_fmea_table


def _req_with_two_failure_modes() -> DraftRequest:
    fms = [
        FailureMode(id="FM-01", function="f1", failure_mode="fm1", effect="e1", severity=7, occurrence=4, detection=3),
        FailureMode(id="FM-02", function="f2", failure_mode="fm2", effect="e2", severity=9, occurrence=2, detection=4),
    ]
    actions = [ActionItem(id="AC-01", failure_mode_id="FM-01", recommended_action="fix it")]
    return DraftRequest(
        document_type="fmea",
        item_or_process="Test Item",
        customer_name="Test Customer",
        engineer_name="Test Engineer",
        failure_modes=fms,
        actions=actions,
    )


def test_rpn_is_arithmetically_consistent_in_rendered_table():
    req = _req_with_two_failure_modes()
    table_html = render_fmea_table(req)
    # FM-01: 7*4*3 = 84 ; FM-02: 9*2*4 = 72
    assert "<td>84</td>" in table_html
    assert "<td>72</td>" in table_html


def test_missing_rating_renders_as_tbd_never_a_number():
    fm = FailureMode(id="FM-03", function="f3", failure_mode="fm3", effect="e3", severity=3, occurrence=5)
    req = DraftRequest(
        document_type="fmea",
        item_or_process="Test Item",
        customer_name="Test Customer",
        engineer_name="Test Engineer",
        failure_modes=[fm],
        actions=[],
    )
    table_html = render_fmea_table(req)
    assert "TBD" in table_html
    # RPN cell must not silently compute an incomplete product.
    assert "<td>15</td>" not in table_html  # 3*5 alone would be wrong-but-plausible if detection defaulted to 1


def test_action_row_traces_to_named_failure_mode():
    req = _req_with_two_failure_modes()
    table_html = render_fmea_table(req)
    assert "<td>AC-01</td>" in table_html
    assert "<td>FM-01</td>" in table_html


def test_instruction_tells_ai_not_to_alter_numbers():
    req = _req_with_two_failure_modes()
    instruction = build_instruction(req)
    assert "do not" in instruction.lower()
    assert "84" in instruction  # the computed RPN is embedded literally
    assert "recalculat" in instruction.lower() or "alter" in instruction.lower()


def test_html_is_escaped_to_avoid_injection_from_free_text_fields():
    fm = FailureMode(id="FM-01", function="<script>bad()</script>", failure_mode="fm", effect="e", severity=1, occurrence=1, detection=1)
    req = DraftRequest(
        document_type="fmea", item_or_process="x", customer_name="c", engineer_name="e",
        failure_modes=[fm], actions=[],
    )
    table_html = render_fmea_table(req)
    assert "<script>" not in table_html
    assert "&lt;script&gt;" in table_html
