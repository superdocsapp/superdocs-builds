from app.models import ContractTerms, Customer, UsagePeriod
from app.true_up import compute_true_up, determine_exception

CUSTOMER = Customer(customer_id="cust-1", name="Acme Renewals Inc.")


def _terms(entitlement: float, rate: float) -> ContractTerms:
    return ContractTerms(
        entitlement_units=entitlement,
        entitlement_quote="entitled to use up to ... (test)",
        monthly_fee=1000.0,
        fee_quote="fee is $1,000.00 (test)",
        overage_rate=rate,
        overage_rate_quote=f"rate of ${rate} per unit (test)",
    )


def test_the_exact_worked_example_from_the_design_doc():
    """entitlement 100, usage 125, overage 25, rate $20/unit -> true_up = 25 * 20 = $500."""
    terms = _terms(entitlement=100, rate=20)
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=125)

    result = compute_true_up(CUSTOMER, terms, usage)

    assert result.overage_units == 25
    assert result.true_up_amount == 500
    assert result.governing_clause_quote == terms.overage_rate_quote


def test_usage_within_entitlement_produces_zero_true_up_and_no_negative_overage():
    terms = _terms(entitlement=100, rate=20)
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=80)

    result = compute_true_up(CUSTOMER, terms, usage)

    assert result.overage_units == 0
    assert result.true_up_amount == 0


def test_usage_exactly_at_entitlement_is_the_zero_boundary_not_a_negative():
    terms = _terms(entitlement=100, rate=20)
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=100)

    result = compute_true_up(CUSTOMER, terms, usage)

    assert result.overage_units == 0
    assert result.true_up_amount == 0


def test_a_true_up_above_zero_is_flagged_as_a_genuine_exception():
    terms = _terms(entitlement=100, rate=20)
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=125)
    result = compute_true_up(CUSTOMER, terms, usage)

    exception = determine_exception(CUSTOMER, result)

    assert exception is not None
    assert exception.reason == "overage_true_up_required"


def test_a_clean_renewal_with_zero_true_up_is_not_an_exception():
    """This is the whole point of the batch design: a clean renewal never reaches a human."""
    terms = _terms(entitlement=100, rate=20)
    usage = UsagePeriod(customer_id="cust-1", period_label="2026-07", units_used=100)
    result = compute_true_up(CUSTOMER, terms, usage)

    exception = determine_exception(CUSTOMER, result)

    assert exception is None
