"""Tests for rfe_response_builder/classify.py."""
from rfe_response_builder.classify import RFECategory, classify, get_profile


def test_classifies_h1b_specialty_occupation_notice():
    notice = (
        "1. The petitioner has not established that the proffered position is a specialty "
        "occupation under 8 CFR 214.2(h)(4)(iii)(A). Provide evidence that a bachelor's "
        "degree is normally required for entry into the position, and submit the labor "
        "condition application."
    )
    result = classify(notice)
    assert result.category == RFECategory.H1B_SPECIALTY_OCCUPATION
    assert result.score >= 3
    assert "specialty occupation" in result.matched_signals


def test_classifies_marriage_bona_fides_notice():
    notice = (
        "1. The record does not establish a bona fide marital relationship. Submit joint "
        "bank statements, a joint lease, and affidavits from third parties attesting to "
        "the relationship."
    )
    result = classify(notice)
    assert result.category == RFECategory.MARRIAGE_BONA_FIDES
    assert "bona fide marital relationship" in result.matched_signals


def test_classifies_eb1a_extraordinary_ability_notice():
    notice = (
        "1. The record does not establish that the beneficiary has sustained national or "
        "international acclaim through original contributions of major significance in the "
        "field, as analyzed under Kazarian."
    )
    result = classify(notice)
    assert result.category == RFECategory.EB1A_EXTRAORDINARY_ABILITY


def test_returns_unknown_for_unrelated_notice():
    notice = "1. Please provide additional documentation regarding the applicant's tax records."
    result = classify(notice)
    assert result.category == RFECategory.UNKNOWN
    assert result.matched_signals == []


def test_returns_unknown_for_weak_single_word_signal():
    # A single incidental "degree" mention should not be enough on its own
    # to classify as H-1B -- the confidence threshold exists precisely to
    # prevent this kind of false positive.
    notice = "1. Please clarify the applicant's degree of involvement in the family business."
    result = classify(notice)
    assert result.category == RFECategory.UNKNOWN


def test_matching_is_case_insensitive_and_whitespace_tolerant():
    notice = "1. The record does NOT establish a\nBONA FIDE   MARITAL\nRELATIONSHIP."
    result = classify(notice)
    assert result.category == RFECategory.MARRIAGE_BONA_FIDES


def test_all_scores_are_returned_for_transparency():
    notice = (
        "1. The record does not establish a bona fide marital relationship. Submit joint "
        "bank statements."
    )
    result = classify(notice)
    assert set(result.all_scores.keys()) == {
        "h1b_specialty_occupation", "marriage_bona_fides", "eb1a_extraordinary_ability",
    }
    assert result.all_scores["marriage_bona_fides"] > result.all_scores["h1b_specialty_occupation"]


def test_get_profile_returns_legal_framework_note_for_each_known_category():
    for category in (RFECategory.H1B_SPECIALTY_OCCUPATION, RFECategory.MARRIAGE_BONA_FIDES,
                      RFECategory.EB1A_EXTRAORDINARY_ABILITY):
        profile = get_profile(category)
        assert profile.legal_framework_note
        assert "CFR" in profile.legal_framework_note or "Kazarian" in profile.legal_framework_note


def test_get_profile_unknown_has_no_note():
    profile = get_profile(RFECategory.UNKNOWN)
    assert profile.legal_framework_note == ""


# --- extract_response_deadline ------------------------------------------------

from rfe_response_builder.classify import extract_response_deadline  # noqa: E402


def test_extract_response_deadline_finds_within_n_days():
    notice = ("You must respond to this Request for Evidence within 87 days from the date "
               "of this notice or your petition may be denied.")
    info = extract_response_deadline(notice)
    assert info.found
    assert info.days == 87
    assert "87 days" in info.matched_sentence


def test_extract_response_deadline_finds_calendar_days_phrasing():
    notice = "A response must be received no later than 30 calendar days from the date of this notice."
    info = extract_response_deadline(notice)
    assert info.found
    assert info.days == 30


def test_extract_response_deadline_returns_not_found_honestly_when_no_phrase_matches():
    notice = "This notice does not mention a deadline at all."
    info = extract_response_deadline(notice)
    assert not info.found
    assert info.days is None
    assert info.matched_sentence is None


def test_extract_response_deadline_prefers_first_matching_pattern():
    notice = ("Please respond within 60 days. A second unrelated sentence mentions "
               "5 days for something else entirely.")
    info = extract_response_deadline(notice)
    assert info.days == 60


# --- notice date extraction / due date calculation (item #10) -----------------

from datetime import date  # noqa: E402

from rfe_response_builder.classify import extract_notice_date  # noqa: E402


def test_extract_notice_date_finds_long_form_date():
    notice = "Notice Date: January 5, 2026\n\nSome other content about the case."
    assert extract_notice_date(notice) == date(2026, 1, 5)


def test_extract_notice_date_finds_numeric_date():
    notice = "Notice Date: 01/05/2026\n\nSome other content about the case."
    assert extract_notice_date(notice) == date(2026, 1, 5)


def test_extract_notice_date_returns_none_when_not_labeled():
    notice = "This notice was mailed on January 5, 2026 but has no labeled Notice Date field."
    assert extract_notice_date(notice) is None


def test_extract_notice_date_returns_none_when_absent():
    notice = "No date information at all in this notice."
    assert extract_notice_date(notice) is None


def test_extract_response_deadline_computes_due_date_when_notice_date_present():
    notice = ("Notice Date: January 5, 2026\n\n"
               "You must respond to this Request for Evidence within 87 days from the date "
               "of this notice or your petition may be denied.")
    info = extract_response_deadline(notice)
    assert info.found
    assert info.notice_date == date(2026, 1, 5)
    assert info.due_date == date(2026, 4, 2)  # Jan 5 + 87 days


def test_extract_response_deadline_due_date_none_when_no_notice_date():
    notice = "You must respond to this Request for Evidence within 87 days from the date of this notice."
    info = extract_response_deadline(notice)
    assert info.found
    assert info.notice_date is None
    assert info.due_date is None


def test_extract_response_deadline_numeric_notice_date_and_calendar_days():
    notice = ("Notice Date: 03/01/2026\n\n"
               "A response must be received no later than 30 calendar days from the date "
               "of this notice.")
    info = extract_response_deadline(notice)
    assert info.notice_date == date(2026, 3, 1)
    assert info.due_date == date(2026, 3, 31)
