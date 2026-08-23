"""Tests for rfe_response_builder/grounding.py."""
from rfe_response_builder.grounding import check_grounding, extract_checkable_facts


def test_extracts_money_amounts():
    assert "$4,500" in extract_checkable_facts("The company paid $4,500 in fees.")
    assert "$1,200.50" in extract_checkable_facts("A refund of $1,200.50 was issued.")


def test_extracts_percentages():
    assert "15%" in extract_checkable_facts("Revenue grew by 15% year over year.")


def test_extracts_years():
    assert "2019" in extract_checkable_facts("The beneficiary joined the company in 2019.")


def test_extracts_durations():
    assert "10 years" in extract_checkable_facts("The beneficiary has 10 years of experience.")
    assert "6 months" in extract_checkable_facts("A probationary period of 6 months applies.")


def test_extracts_counts():
    assert "50 employees" in extract_checkable_facts("The company has 50 employees.")


def test_extracts_multi_word_proper_nouns():
    facts = extract_checkable_facts("The beneficiary worked at Acme Robotics Corp for years.")
    assert "Acme Robotics Corp" in facts


def test_does_not_flag_single_capitalized_sentence_start_word():
    facts = extract_checkable_facts("The record clearly establishes the claim.")
    assert not any(len(f.split()) < 2 for f in facts)


def test_check_grounding_no_concerns_when_everything_traces_to_source():
    source = ["The beneficiary has 10 years of experience at Acme Robotics Corp."]
    draft = "The beneficiary brings 10 years of experience at Acme Robotics Corp to this role."
    result = check_grounding(draft, source)
    assert not result.has_concerns
    assert result.ungrounded_facts == []


def test_check_grounding_flags_fabricated_numeric_details():
    source = ["The beneficiary has 10 years of experience at Acme Robotics Corp."]
    draft = "The beneficiary has 15 years of experience and earned $50,000 in bonuses in 2019."
    result = check_grounding(draft, source)
    assert result.has_concerns
    assert "15 years" in result.ungrounded_facts
    assert "$50,000" in result.ungrounded_facts
    assert "2019" in result.ungrounded_facts


def test_check_grounding_flags_fabricated_organization_name():
    source = ["The beneficiary has worked in the aerospace industry."]
    draft = "The beneficiary previously worked at Fictional Aerospace Consortium."
    result = check_grounding(draft, source)
    assert "Fictional Aerospace Consortium" in result.ungrounded_facts


def test_check_grounding_handles_empty_draft():
    result = check_grounding("", ["some source text"])
    assert not result.has_concerns
    assert result.total_facts_checked == 0


def test_check_grounding_is_case_and_whitespace_insensitive():
    source = ["The beneficiary earned $4,500 in    2019."]
    draft = "In 2019 the beneficiary earned $4,500."
    result = check_grounding(draft, source)
    assert not result.has_concerns
