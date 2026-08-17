from core.normalize import (
    addresses_match,
    names_compatible_under_middle_initial_rule,
    normalize_boolean,
    normalize_money,
    normalize_percentage,
    normalize_term_months,
)


def test_normalize_money():
    assert normalize_money("$420,000.00") == 420000.0
    assert normalize_money("$2,850.00") == 2850.0


def test_normalize_percentage():
    assert normalize_percentage("6.500%") == 6.5
    assert normalize_percentage("6.500% per annum") == 6.5


def test_normalize_term():
    assert normalize_term_months("30 years") == 360
    assert normalize_term_months("360 months") == 360
    assert normalize_term_months("360 monthly payments") == 360


def test_normalize_escrow():
    assert normalize_boolean("Yes") is True
    assert normalize_boolean("Required") is True
    assert normalize_boolean("No") is False


def test_middle_initial_rule():
    assert names_compatible_under_middle_initial_rule(
        "John A. Carter",
        "John Carter",
    )

    assert not names_compatible_under_middle_initial_rule(
        "John A. Carter",
        "John Smith",
    )


def test_address_abbreviation_normalization():
    assert addresses_match(
        "812 Cedar Grove Drive, Austin, TX 78704",
        "812 Cedar Grove Dr., Austin, TX 78704",
    )

    assert addresses_match(
        "812 Cedar Grove Drive, Austin, Texas 78704",
        "812 Cedar Grove Dr., Austin, TX 78704",
    )


def test_different_address_does_not_match():
    assert not addresses_match(
        "812 Cedar Grove Drive, Austin, TX 78704",
        "814 Cedar Grove Drive, Austin, TX 78704",
    )