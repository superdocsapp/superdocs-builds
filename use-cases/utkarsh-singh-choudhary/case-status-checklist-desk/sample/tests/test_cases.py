from datetime import date

import pytest

from case_status_desk.cases import Case, RequiredDocument, build_letter_instruction


def make_case(**overrides):
    defaults = dict(
        case_id="CASE-TEST",
        client_name="Test Client",
        case_type="employment-based petition",
        stage="documents_pending",
        required_documents=[
            RequiredDocument(name="Degree Certificate", form_type="certified copy", received=False),
            RequiredDocument(name="Pay Stubs", form_type="last 3 months", received=True),
        ],
    )
    defaults.update(overrides)
    return Case(**defaults)


def test_unknown_stage_rejected():
    with pytest.raises(ValueError):
        make_case(stage="made_up_stage")


def test_outstanding_documents_only_lists_unreceived():
    case = make_case()
    outstanding = case.outstanding_documents()
    assert len(outstanding) == 1
    assert outstanding[0].name == "Degree Certificate"


def test_fully_documented_when_all_received():
    case = make_case(required_documents=[RequiredDocument(name="X", form_type="Y", received=True)])
    assert case.is_fully_documented() is True


def test_checklist_regenerates_from_current_state_not_stale():
    """The checklist must reflect live state -- flipping `received` changes
    the outstanding list, proving it's derived each call, not cached."""
    doc = RequiredDocument(name="Degree Certificate", form_type="certified copy", received=False)
    case = make_case(required_documents=[doc])
    assert len(case.outstanding_documents()) == 1
    doc.received = True
    assert len(case.outstanding_documents()) == 0


def test_stage_language_is_exact_and_from_approved_set():
    case = make_case(stage="rfe_received")
    assert "RFE" in case.stage_summary or "additional evidence" in case.stage_summary
    assert case.stage_next_step  # never empty


def test_letter_instruction_embeds_exact_stage_language_and_checklist():
    case = make_case()
    instruction = build_letter_instruction(case)
    assert case.stage_summary in instruction
    assert case.stage_next_step in instruction
    assert "Degree Certificate (certified copy)" in instruction
    # received doc must NOT appear in the outstanding checklist
    assert "Pay Stubs" not in instruction


def test_letter_instruction_with_no_outstanding_docs_says_so():
    case = make_case(required_documents=[RequiredDocument(name="X", form_type="Y", received=True)])
    instruction = build_letter_instruction(case)
    assert "none -- your file is complete" in instruction


def test_letter_instruction_includes_due_date_when_present():
    case = make_case(
        required_documents=[
            RequiredDocument(name="W-2", form_type="IRS Form W-2", received=False, due_date=date(2026, 9, 1))
        ]
    )
    instruction = build_letter_instruction(case)
    assert "due 2026-09-01" in instruction
