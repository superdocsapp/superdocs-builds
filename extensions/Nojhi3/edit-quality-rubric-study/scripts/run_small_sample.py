"""Small-sample run: 6 cases, budget cap stated before the run, actual spend printed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.budget import BudgetGuard
from app.pipeline import EditRunner, load_cases
from app.superdocs_client import SuperDocsClient

CAP = 60
budget = BudgetGuard(cap_ops=CAP)
client = SuperDocsClient(budget=budget)
cases = load_cases()[:6]

print(f"CAP STATED BEFORE THIS RUN: {CAP} operations")
print(f"Estimated cost: {len(cases)} edits x 1 op + retries <= ~{len(cases) + 4} ops")
print(f"Cases: {[c['case_id'] for c in cases]}")
print("Starting edit pipeline...")

runner = EditRunner(client)
summary = runner.run_all([c["case_id"] for c in cases])
for r in summary["results"]:
    print(f"  {r['case_id']}: {r['status']} pending_changes={r.get('pending_change_count')}")

print()
print("ACTUAL SPEND:", budget.report()["spent_ops"], "ops")
for f in summary["failed"]:
    print("FAILED:", f)