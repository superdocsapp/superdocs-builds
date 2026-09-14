"""Synthetic renewal cohort - invented clients and data, exactly as the task brief expects ('Where your
build needs a client, a company, or data, invent them'). Four customers chosen deliberately to exercise
every path the batch runner needs to prove: two clean renewals, one genuine overage exception, and one
contract with a missing governing clause (the other exception trigger)."""

from app.models import Customer, UsagePeriod
from app.batch import CohortItem

_ACME = """MASTER SERVICES AGREEMENT

This Agreement is entered into as of January 1, 2026, between Acme Robotics Inc. ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 10,000 (ten thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $8,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.50 per compute unit above the Monthly Entitlement.
"""

_BRIGHTLEAF = """MASTER SERVICES AGREEMENT

This Agreement is entered into as of February 1, 2026, between Brightleaf Analytics LLC ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 25,000 (twenty-five thousand) compute units per month
("Monthly Entitlement") under this Agreement.

2.2 The fee for the Monthly Entitlement is $18,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.20 per compute unit above the Monthly Entitlement.
"""

_CASCADE = """MASTER SERVICES AGREEMENT

This Agreement is entered into as of March 1, 2026, between Cascade Logistics Corp. ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 5,000 (five thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $4,500.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $2.00 per compute unit above the Monthly Entitlement.
"""

# Deliberately missing a 3.1 overage-rate clause - exercises the clause_not_found exception path with real
# (if synthetic) messy data, not a hand-picked always-clean corpus.
_DRIFTWOOD = """MASTER SERVICES AGREEMENT

This Agreement is entered into as of April 1, 2026, between Driftwood Media Group ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 8,000 (eight thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $6,000.00 per month, payable in advance.
"""


def load_sample_cohort() -> list[CohortItem]:
    return [
        CohortItem(
            customer=Customer("acme", "Acme Robotics Inc."),
            contract_text=_ACME,
            usage=UsagePeriod("acme", "2026-07", units_used=9_200),  # clean: under 10,000
            new_entitlement_units=12_000,
        ),
        CohortItem(
            customer=Customer("brightleaf", "Brightleaf Analytics LLC"),
            contract_text=_BRIGHTLEAF,
            usage=UsagePeriod("brightleaf", "2026-07", units_used=31_500),  # overage: exception
            new_entitlement_units=30_000,
        ),
        CohortItem(
            customer=Customer("cascade", "Cascade Logistics Corp."),
            contract_text=_CASCADE,
            usage=UsagePeriod("cascade", "2026-07", units_used=4_100),  # clean: under 5,000
            new_entitlement_units=6_000,
        ),
        CohortItem(
            customer=Customer("driftwood", "Driftwood Media Group"),
            contract_text=_DRIFTWOOD,
            usage=UsagePeriod("driftwood", "2026-07", units_used=7_500),  # exception: no overage clause found
            new_entitlement_units=10_000,
        ),
    ]
