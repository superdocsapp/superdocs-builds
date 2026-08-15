from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st
from pydantic import ValidationError

from payment_plan_agreement.engine import PaymentPlanService
from payment_plan_agreement.models import Frequency, LateFee, LateFeeKind


def test_equal_allocation_and_upfront(request_factory):
    plan = PaymentPlanService().calculate(request_factory())
    assert [x.amount for x in plan.installments] == [Decimal("225.00")] * 4
    assert plan.terms.upfront_payment + plan.total_scheduled == plan.terms.original_balance
    assert plan.installments[-1].balance_after == 0


def test_remainder_goes_to_earliest(request_factory):
    plan = PaymentPlanService().calculate(request_factory(original_balance=Decimal("100.00"), upfront_payment=0, installment_count=3))
    assert [x.amount for x in plan.installments] == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]


@pytest.mark.parametrize(("frequency", "expected"), [(Frequency.WEEKLY, date(2026, 2, 7)), (Frequency.BIWEEKLY, date(2026, 2, 14))])
def test_weekly_dates(request_factory, frequency, expected):
    plan = PaymentPlanService().calculate(request_factory(first_due_date=date(2026, 1, 31), agreement_date=date(2026, 1, 1), frequency=frequency, installment_count=2))
    assert plan.installments[1].due_date == expected


def test_month_end_clamps_from_original_day(request_factory):
    plan = PaymentPlanService().calculate(request_factory(first_due_date=date(2024, 1, 31), agreement_date=date(2024, 1, 1), installment_count=4))
    assert [x.due_date for x in plan.installments] == [date(2024, 1, 31), date(2024, 2, 29), date(2024, 3, 31), date(2024, 4, 30)]


@pytest.mark.parametrize("changes", [{"original_balance": 0}, {"original_balance": -1}, {"upfront_payment": Decimal("1000")}, {"first_due_date": date(2020, 1, 1)}])
def test_invalid_terms_fail_before_external_work(request_factory, changes):
    with pytest.raises(ValueError): PaymentPlanService().calculate(request_factory(**changes))


def test_model_validation_and_currency(request_factory):
    with pytest.raises(ValidationError): request_factory(installment_count=0)
    with pytest.raises(ValueError): PaymentPlanService().calculate(request_factory(currency="XYZ"))
    with pytest.raises(ValidationError): request_factory(late_fee=LateFee(kind=LateFeeKind.PERCENT, percent=Decimal("30")))


def test_fingerprint_and_projection(request_factory):
    service = PaymentPlanService(); first = service.calculate(request_factory()); second = service.calculate(request_factory())
    changed = service.calculate(request_factory(first_due_date=date(2026, 9, 16)))
    assert first.semantic_fingerprint == second.semantic_fingerprint
    assert first.semantic_fingerprint != changed.semantic_fingerprint
    projection = service.project(first)
    assert len(projection.schedule_rows) == 4
    assert projection.schedule_rows[-1]["due_date"] == first.final_due_date.isoformat()


@given(total=st.integers(min_value=1, max_value=10_000_000), count=st.integers(min_value=1, max_value=120))
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_exact_allocation(request_factory, total, count):
    if count > total: return
    value = Decimal(total) / 100
    plan = PaymentPlanService().calculate(request_factory(original_balance=value, upfront_payment=0, installment_count=count))
    assert len(plan.installments) == count
    assert all(x.amount > 0 for x in plan.installments)
    assert sum((x.amount for x in plan.installments), Decimal(0)) == value
    assert plan.installments[-1].balance_after == 0
