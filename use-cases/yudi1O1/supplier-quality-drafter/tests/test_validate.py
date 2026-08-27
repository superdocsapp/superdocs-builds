from supplier_quality_drafter.models import ActionItem, DraftRequest, FailureMode
from supplier_quality_drafter.validate import validate_request


def _base_request(**overrides) -> DraftRequest:
    defaults = dict(
        document_type="fmea",
        item_or_process="Test Process",
        customer_name="Test Customer",
        engineer_name="Test Engineer",
        failure_modes=[
            FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=5, occurrence=5, detection=5)
        ],
        actions=[ActionItem(id="AC-01", failure_mode_id="FM-01", recommended_action="do something")],
    )
    defaults.update(overrides)
    return DraftRequest(**defaults)


def test_clean_input_has_no_blocking_findings():
    req = _base_request()
    result = validate_request(req)
    assert result.ok_to_draft
    assert result.blocking == []


def test_missing_severity_is_blocking_not_invented():
    fm = FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", occurrence=5, detection=5)
    req = _base_request(failure_modes=[fm], actions=[])
    result = validate_request(req)
    assert not result.ok_to_draft
    messages = [f.message for f in result.blocking]
    assert any("severity" in m for m in messages)
    # Crucially: the failure mode's rpn() must be None, not a guessed number.
    assert fm.rpn() is None


def test_missing_occurrence_and_detection_both_flagged():
    fm = FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=5)
    req = _base_request(failure_modes=[fm], actions=[])
    result = validate_request(req)
    locations_and_messages = "\n".join(f"{f.location}: {f.message}" for f in result.blocking)
    assert "occurrence" in locations_and_messages
    assert "detection" in locations_and_messages


def test_out_of_range_rating_is_blocking():
    fm = FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=11, occurrence=5, detection=5)
    req = _base_request(failure_modes=[fm], actions=[])
    result = validate_request(req)
    assert not result.ok_to_draft
    assert any("out of the 1-10" in f.message for f in result.blocking)


def test_action_must_reference_existing_failure_mode():
    req = _base_request(actions=[ActionItem(id="AC-01", failure_mode_id="FM-99", recommended_action="x")])
    result = validate_request(req)
    assert not result.ok_to_draft
    assert any("FM-99" in f.message for f in result.blocking)


def test_action_with_no_failure_mode_id_is_blocking():
    req = _base_request(actions=[ActionItem(id="AC-01", failure_mode_id="", recommended_action="x")])
    result = validate_request(req)
    assert not result.ok_to_draft


def test_duplicate_failure_mode_ids_blocking():
    fms = [
        FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=1, occurrence=1, detection=1),
        FailureMode(id="FM-01", function="g", failure_mode="fm2", effect="e2", severity=2, occurrence=2, detection=2),
    ]
    req = _base_request(failure_modes=fms, actions=[])
    result = validate_request(req)
    assert not result.ok_to_draft
    assert any("Duplicate" in f.message for f in result.blocking)


def test_high_rpn_with_no_linked_action_is_a_warning_not_blocking():
    fm = FailureMode(id="FM-01", function="f", failure_mode="fm", effect="e", severity=9, occurrence=9, detection=9)
    req = _base_request(failure_modes=[fm], actions=[])
    result = validate_request(req)
    assert result.ok_to_draft  # warnings don't block
    assert any(f.severity == "warning" and "RPN" in f.message for f in result.findings)


def test_empty_failure_modes_blocking_for_fmea():
    req = _base_request(failure_modes=[], actions=[])
    result = validate_request(req)
    assert not result.ok_to_draft


def test_ppap_missing_submission_level_blocking():
    from supplier_quality_drafter.models import PPAPInputs

    req = _base_request(
        document_type="ppap",
        ppap=PPAPInputs(
            part_number="P1", part_name="Part", supplier_name="S", customer_name="C",
            reason_for_submission="annual revalidation",
        ),
    )
    result = validate_request(req)
    assert not result.ok_to_draft
    assert any("submission_level" in f.location for f in result.blocking)


def test_8d_missing_root_cause_blocking():
    from supplier_quality_drafter.models import EightDInputs

    req = _base_request(
        document_type="8d",
        eightd=EightDInputs(d2_problem_description="a problem", d5_permanent_corrective_actions="a fix"),
    )
    result = validate_request(req)
    assert not result.ok_to_draft
    assert any("d4_root_cause" in f.location for f in result.blocking)
