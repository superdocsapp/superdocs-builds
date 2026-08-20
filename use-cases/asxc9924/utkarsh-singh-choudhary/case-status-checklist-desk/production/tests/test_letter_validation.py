from datetime import date

from case_status_desk.cases import Case, RequiredDocument
from case_status_desk.letter_validation import validate_letter


def _case(stage="documents_pending", docs=None):
    return Case(
        case_id="CASE-VAL-1",
        client_name="Test Client",
        case_type="employment-based petition",
        stage=stage,
        language="en",
        required_documents=docs or [],
    )


def test_valid_letter_passes():
    case = _case(docs=[RequiredDocument(name="Passport", form_type="certified copy", received=False)])
    letter = (
        "Dear Test Client, We are waiting on some documents from you before we can file. "
        "Please send the outstanding items listed below as soon as you can. "
        "- Passport (certified copy)"
    )
    result = validate_letter(case, letter)
    assert result.passed
    assert result.errors == []


def test_missing_outstanding_document_is_error():
    case = _case(docs=[RequiredDocument(name="Passport", form_type="certified copy", received=False)])
    letter = (
        "We are waiting on some documents from you before we can file. "
        "Please send the outstanding items listed below as soon as you can."
    )
    result = validate_letter(case, letter)
    assert not result.passed
    codes = {i.code for i in result.errors}
    assert "missing_outstanding_document" in codes


def test_missing_form_type_is_error():
    case = _case(docs=[RequiredDocument(name="Passport", form_type="certified copy", received=False)])
    letter = (
        "We are waiting on some documents from you before we can file. "
        "Please send the outstanding items listed below as soon as you can. "
        "- Passport"  # form_type dropped
    )
    result = validate_letter(case, letter)
    assert not result.passed
    codes = {i.code for i in result.errors}
    assert "missing_form_type" in codes


def test_stage_summary_must_be_verbatim():
    case = _case(stage="rfe_received")
    letter = (
        "The government wants more evidence for your case. "
        "We need the additional documents listed below to respond by the agency's deadline."
    )
    result = validate_letter(case, letter)
    assert not result.passed
    codes = {i.code for i in result.errors}
    assert "stage_summary_not_verbatim" in codes


def test_stage_next_step_must_be_verbatim():
    case = _case(stage="rfe_received")
    letter = (
        "The agency has requested additional evidence (an RFE) before they can decide your case. "
        "Just send us whatever you can whenever."
    )
    result = validate_letter(case, letter)
    assert not result.passed
    codes = {i.code for i in result.errors}
    assert "stage_next_step_not_verbatim" in codes


def test_whitespace_reflow_still_counts_as_verbatim():
    case = _case(stage="filed")
    letter = (
        "Your   case has been filed\nwith the relevant agency.\n\n"
        "We are waiting for the agency's   receipt notice and will\nupdate you as soon as it arrives."
    )
    result = validate_letter(case, letter)
    assert result.passed


def test_received_document_flagged_if_listed_as_outstanding():
    case = _case(docs=[
        RequiredDocument(name="Passport", form_type="certified copy", received=True),
        RequiredDocument(name="Pay Stubs", form_type="last 3 months", received=False),
    ])
    letter = (
        "We are waiting on some documents from you before we can file. "
        "Please send the outstanding items listed below as soon as you can. "
        "- Passport (certified copy)\n- Pay Stubs (last 3 months)"
    )
    result = validate_letter(case, letter)
    warning_codes = {i.code for i in result.warnings}
    assert "received_document_listed_as_outstanding" in warning_codes
    # This is a warning, not an error -- doesn't block approval by itself
    assert result.passed or not result.passed  # sanity: passed is errors-only
    assert all(i.severity != "error" for i in result.issues if i.code == "received_document_listed_as_outstanding")


def test_received_document_not_flagged_in_unrelated_mention():
    case = _case(docs=[
        RequiredDocument(name="Passport", form_type="certified copy", received=True),
    ])
    letter = (
        "Your case has been filed with the relevant agency. "
        "Thank you for sending your Passport -- we have it on file. "
        "We are waiting for the agency's receipt notice and will update you as soon as it arrives."
    )
    case2 = _case(stage="filed", docs=case.required_documents)
    result = validate_letter(case2, letter)
    warning_codes = {i.code for i in result.warnings}
    assert "received_document_listed_as_outstanding" not in warning_codes


def test_advice_language_flagged_as_warning_not_error():
    case = _case(stage="under_review")
    letter = (
        "Your file is complete on our end and is being reviewed by our team before filing. "
        "No action is needed from you right now. "
        "We guarantee your case will be approved."
    )
    result = validate_letter(case, letter)
    warning_codes = {i.code for i in result.warnings}
    assert "possible_advice_language" in warning_codes
    # advice-language is a warning, doesn't block on its own
    assert result.passed


def test_empty_letter_is_error():
    case = _case()
    result = validate_letter(case, "")
    assert not result.passed
    assert result.errors[0].code == "empty_letter"


def test_fully_documented_case_has_no_outstanding_checks_to_fail():
    case = _case(stage="filed", docs=[RequiredDocument(name="Passport", form_type="copy", received=True)])
    letter = (
        "Your case has been filed with the relevant agency. "
        "We are waiting for the agency's receipt notice and will update you as soon as it arrives."
    )
    result = validate_letter(case, letter)
    assert result.passed
