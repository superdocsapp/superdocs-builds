from demo import run_demo


def test_process_kill_resume_is_idempotent() -> None:
    proof = run_demo()
    assert proof["process_was_killed"] is True
    assert proof["fresh_recovery_process"] is True
    assert proof["provider_session_restored"] is True
    assert proof["provider_job_restored"] is True
    assert proof["first_decision_preserved"] is True
    assert proof["second_was_pending_after_restart"] is True
    assert proof["mixed_decisions_preserved"] is True
    assert proof["document_state_preserved"] is True
    assert proof["approved_change_applied"] is True
    assert proof["rejected_change_not_applied"] is True
    assert proof["provider_document_updates"] == 1
    assert proof["resumed_status"] == "COMPLETE"
    assert proof["duplicate_logical_effects"] == 0
    assert proof["pre_and_post_crash_audit_present"] is True
    assert proof["export_valid"] is True
    assert proof["export_bytes"] > 500
