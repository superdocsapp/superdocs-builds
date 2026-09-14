import pytest

from app.clause_extraction import ClauseNotFoundError, extract_contract_terms

SAMPLE_CONTRACT = """MASTER SERVICES AGREEMENT (SAMPLE)

This Agreement is entered into as of January 1, 2026, between Acme Renewals Inc. ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 10,000 (ten thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $8,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.50 per compute unit above the Monthly Entitlement.
"""


def test_extracts_all_three_governing_facts_with_exact_quotes():
    terms = extract_contract_terms(SAMPLE_CONTRACT)

    assert terms.entitlement_units == 10_000
    assert "entitled to use up to 10,000" in terms.entitlement_quote

    assert terms.monthly_fee == 8_000
    assert "$8,000.00" in terms.fee_quote

    assert terms.overage_rate == 1.5
    assert "$1.50 per compute unit" in terms.overage_rate_quote

    # Every quote must be an exact substring of the source contract, never a paraphrase - that's the
    # entire point of this build. Verified directly, not assumed.
    assert terms.entitlement_quote in SAMPLE_CONTRACT
    assert terms.fee_quote in SAMPLE_CONTRACT
    assert terms.overage_rate_quote in SAMPLE_CONTRACT

    # Regression guard for a real bug found during live verification against the real SuperDocs API: each
    # clause's own section number ("2.1", "2.2", "3.1") contains a period, which the extraction regex was
    # treating as a sentence-ending period - silently dropping the leading section number from every
    # quote ("3.1 If Customer..." came back as "1 If Customer..."). The substring checks above never
    # caught this since they don't check where the quote STARTS.
    assert terms.entitlement_quote.startswith("2.1 Customer is entitled")
    assert terms.fee_quote.startswith("2.2 The fee")
    assert terms.overage_rate_quote.startswith("3.1 If Customer usage exceeds")


def test_missing_entitlement_clause_raises_rather_than_guessing():
    contract_without_entitlement = "This contract has no entitlement clause at all, just prose."
    with pytest.raises(ClauseNotFoundError) as exc_info:
        extract_contract_terms(contract_without_entitlement)
    assert exc_info.value.field_name == "entitlement_units"


def test_missing_overage_rate_raises_the_specific_field_name():
    contract_missing_rate = """
    2.1 Customer is entitled to use up to 5,000 (five thousand) compute units per month
    ("Monthly Entitlement") under this Agreement.

    2.2 The fee for the Monthly Entitlement is $3,000.00 per month, payable in advance.
    """
    with pytest.raises(ClauseNotFoundError) as exc_info:
        extract_contract_terms(contract_missing_rate)
    assert exc_info.value.field_name == "overage_rate"
