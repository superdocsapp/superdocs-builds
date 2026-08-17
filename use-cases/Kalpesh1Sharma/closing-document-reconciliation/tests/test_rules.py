from core.models import FileRule
from core.rules import (
    numeric_tolerance_from_rule,
    rule_supports_address_abbreviations,
    rule_supports_middle_initial_omission,
)


def rule(text: str, rule_id: str = "R-TEST") -> FileRule:
    return FileRule(
        rule_id=rule_id,
        rule_text=text,
        source_document="underwriting_approval.docx",
        supporting_quote=text,
    )


def test_exact_match_rule_derives_zero_tolerance():
    assert numeric_tolerance_from_rule(
        rule("The final interest rate must exactly match the approved rate.")
    ) == 0


def test_up_to_threshold_is_parsed_from_actual_rule_text():
    assert numeric_tolerance_from_rule(
        rule(
            "A Title & Settlement Services fee difference of up to "
            "$100.00 from the Loan Estimate is tolerable."
        )
    ) == 100


def test_greater_than_threshold_is_parsed_from_actual_rule_text():
    assert numeric_tolerance_from_rule(
        rule(
            "A final cash-to-close difference greater than $500.00 "
            "from the Loan Estimate requires review."
        )
    ) == 500


def test_unstructured_numeric_rule_does_not_invent_tolerance():
    assert numeric_tolerance_from_rule(
        rule("Fees should be reasonable.")
    ) is None


def test_text_normalizations_are_enabled_by_rule_semantics():
    assert rule_supports_middle_initial_omission(
        rule(
            "A borrower's middle initial may be omitted if the first "
            "and last names otherwise match."
        )
    )

    assert rule_supports_address_abbreviations(
        rule(
            "Standard postal street abbreviations do not constitute a "
            "property-address variance."
        )
    )
