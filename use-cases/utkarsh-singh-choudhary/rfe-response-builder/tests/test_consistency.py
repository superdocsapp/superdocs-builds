"""Tests for rfe_response_builder/consistency.py."""
from rfe_response_builder.consistency import check_cross_item_consistency


def test_flags_contradictory_years_for_shared_entity():
    items = [
        ("1", "The beneficiary worked at Acme Robotics Corp from 2018 to 2022 as lead engineer."),
        ("3", "At Acme Robotics Corp, the beneficiary began work in 2019 and stayed until 2023."),
    ]
    flags = check_cross_item_consistency(items)
    assert len(flags) == 1
    flag = flags[0]
    assert flag.request_id_a == "1"
    assert flag.request_id_b == "3"
    assert flag.shared_entity == "Acme Robotics Corp"
    assert set(flag.facts_a) == {"2018", "2022"}
    assert set(flag.facts_b) == {"2019", "2023"}


def test_no_flag_when_no_shared_entity():
    items = [
        ("1", "The beneficiary worked at Acme Robotics Corp starting in 2018."),
        ("2", "The beneficiary later joined Beta Aerospace Inc in 2022."),
    ]
    assert check_cross_item_consistency(items) == []


def test_no_flag_when_facts_agree():
    items = [
        ("1", "The beneficiary worked at Acme Robotics Corp starting in 2018."),
        ("2", "Acme Robotics Corp hired the beneficiary in 2018 as a specialist."),
    ]
    assert check_cross_item_consistency(items) == []


def test_no_flag_when_one_side_simply_does_not_mention_a_fact():
    """A fact present in one item and absent in the other is not a
    contradiction -- it's just not discussed there. Only flag when BOTH
    sides state something and those somethings differ."""
    items = [
        ("1", "The beneficiary worked at Acme Robotics Corp."),  # no year mentioned
        ("2", "Acme Robotics Corp confirmed the beneficiary's role began in 2019."),
    ]
    assert check_cross_item_consistency(items) == []


def test_no_flags_for_single_item():
    items = [("1", "The beneficiary worked at Acme Robotics Corp from 2018 to 2022.")]
    assert check_cross_item_consistency(items) == []


def test_no_flags_for_empty_list():
    assert check_cross_item_consistency([]) == []


def test_flags_multiple_pairs_independently():
    items = [
        ("1", "Acme Robotics Corp employed the beneficiary starting in 2018."),
        ("2", "Acme Robotics Corp records show the beneficiary joined in 2020."),
        ("3", "The beneficiary also consulted for Beta Aerospace Inc in 2015."),
    ]
    flags = check_cross_item_consistency(items)
    assert len(flags) == 1
    assert {flags[0].request_id_a, flags[0].request_id_b} == {"1", "2"}


def test_flags_dollar_amount_contradictions_too():
    items = [
        ("1", "Global Tech Partners paid the beneficiary a signing bonus of $10,000."),
        ("2", "According to records, Global Tech Partners issued a bonus of $25,000 to the beneficiary."),
    ]
    flags = check_cross_item_consistency(items)
    assert len(flags) == 1
    assert "$10,000" in flags[0].facts_a
    assert "$25,000" in flags[0].facts_b
