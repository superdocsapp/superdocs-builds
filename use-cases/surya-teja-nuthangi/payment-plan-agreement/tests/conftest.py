from datetime import date
from decimal import Decimal

import pytest

from payment_plan_agreement.models import CreatePlanRequest, Frequency, LateFee, Party, PlanTerms


@pytest.fixture
def request_factory():
    def make(**changes):
        values = dict(currency="USD", original_balance=Decimal("1000.00"), upfront_payment=Decimal("100.00"), installment_count=4, frequency=Frequency.MONTHLY, first_due_date=date(2026, 9, 15), agreement_date=date(2026, 8, 14), late_fee=LateFee(), reference_id="INV-100")
        values.update(changes)
        return CreatePlanRequest(creditor=Party(legal_name="Example Health Services"), debtor=Party(legal_name="Alex Morgan"), terms=PlanTerms(**values))
    return make
