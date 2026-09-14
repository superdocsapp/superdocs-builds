"""One-off, real-API verification script - not part of the test suite (which stays offline/fake per the
round's own standard). Run manually, once, with a real SUPERDOCS_API_KEY, to prove the actual integration
works before committing/pushing. Deliberately touches only ONE customer, not the full cohort - budgeting
real operations against a metered free-tier account, per the task brief's own explicit warning.
"""

import os

from app.models import Customer, UsagePeriod
from app.renewal_engine import PendingHumanDecision, apply_human_decision, start_renewal
from app.superdocs_client import RealSuperDocsClient

CONTRACT_TEXT = """MASTER SERVICES AGREEMENT (SAMPLE)

This Agreement is entered into as of January 1, 2026, between Acme Renewals Inc. ("Customer") and
Vertex Cloud Partners LLC ("Vendor").

2.1 Customer is entitled to use up to 10,000 (ten thousand) compute units per month ("Monthly Entitlement")
under this Agreement.

2.2 The fee for the Monthly Entitlement is $8,000.00 per month, payable in advance.

3.1 If Customer usage exceeds the Monthly Entitlement in any given month, Vendor shall invoice Customer for
the excess usage at a rate of $1.50 per compute unit above the Monthly Entitlement.
"""

api_key = os.environ.get("SUPERDOCS_API_KEY")
if not api_key:
    raise SystemExit("SUPERDOCS_API_KEY not set")

client = RealSuperDocsClient(api_key)

# Test 1 (clean renewal, approve_all path) already verified in a prior run - skipped here to conserve
# real operations against the metered free-tier account, per the task brief's own warning.

print("=== Test 2: overage renewal (real HITL approval), re-run with the wait-for-completion fix ===")
customer2 = Customer("verify-3", "Real API Verification Customer 2")
usage_overage = UsagePeriod("verify-3", "2026-07", units_used=15_000)
try:
    start_renewal(client, customer2, CONTRACT_TEXT, usage_overage, new_entitlement_units=12_000)
    print("ERROR: expected PendingHumanDecision to be raised")
except PendingHumanDecision as pending:
    print("PendingHumanDecision raised correctly")
    print("true_up_amount:", pending.package.true_up.true_up_amount)
    print("governing_clause_quote:", pending.package.true_up.governing_clause_quote)
    print("job_id:", pending.job_id, "change_id:", pending.change_id)

    result = apply_human_decision(client, pending.package, pending.job_id, pending.change_id, approved=True)
    print("after approval, exported summary contains '12,000':", "12,000" in (result.exported_summary_markdown or ""))
    print()
    print("--- exported markdown after approval ---")
    print(result.exported_summary_markdown)

client.close()
