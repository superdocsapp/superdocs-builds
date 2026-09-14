"""One-off, real-API verification for the three fixes closing real gaps found auditing against the task
brief: the images surface, the Multi-document surface, and surfacing the actual proposed amendment content
to a reviewer. Run manually, once, before committing/pushing - not part of the test suite. Deliberately one
clean customer + one overage customer, not a full cohort, per the brief's own operation-budget warning.
"""

import os

from app.models import Customer, UsagePeriod
from app.renewal_engine import PendingHumanDecision, start_renewal
from app.superdocs_client import RealSuperDocsClient

CONTRACT_TEXT = """MASTER SERVICES AGREEMENT (SAMPLE)

This Agreement is entered into as of January 1, 2026, between Verify Images Inc. ("Customer") and
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

print("=== Test 1: clean renewal - new amendment message references the uploaded usage report ===")
print("(this is exactly the class of change that caused duplication when referencing a template earlier -")
print(" must be re-verified for real, not assumed safe by analogy)")
customer1 = Customer("verify-img-1", "Verify Images Clean Co")
usage_clean = UsagePeriod("verify-img-1", "2026-07", units_used=9_000)
clean = start_renewal(client, customer1, CONTRACT_TEXT, usage_clean, new_entitlement_units=12_000)
print("usage_chart_url:", clean.usage_chart_url)
print("usage_report_uploaded:", clean.usage_report_uploaded)
print("'12,000' in export:", "12,000" in (clean.exported_summary_markdown or ""))
print("'10,000' in export (should be False):", "10,000" in (clean.exported_summary_markdown or ""))
print("amendment section count in export:", (clean.exported_summary_markdown or "").lower().count("amendment"))
print()
print("--- exported markdown (clean path) ---")
print(clean.exported_summary_markdown)
print()

print("=== Test 2: overage renewal - inspect the real old_html/new_html/ai_explanation shape ===")
customer2 = Customer("verify-img-2", "Verify Images Overage Co")
usage_overage = UsagePeriod("verify-img-2", "2026-07", units_used=15_000)
try:
    start_renewal(client, customer2, CONTRACT_TEXT, usage_overage, new_entitlement_units=12_000)
    print("ERROR: expected PendingHumanDecision")
except PendingHumanDecision as pending:
    print("usage_chart_url:", pending.package.usage_chart_url)
    print("old_html repr:", repr(pending.old_html))
    print("new_html repr:", repr(pending.new_html))
    print("ai_explanation repr:", repr(pending.ai_explanation))

client.close()
