"""
Synthetic collective bargaining agreement + two position papers with
deliberate, specific disagreements — so redline rounds have something real
to reconcile and the open-items tracker has genuine multi-round material.
All content fabricated. No real employer, union, or person's data.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"

CBA_DRAFT = """COLLECTIVE BARGAINING AGREEMENT (DRAFT)

Between Northfield Manufacturing Co. ("Employer") and Local 214 United
Production Workers ("Union").

Article 3 — Wages
Base hourly rate for Grade II production workers shall be $24.00/hour,
effective upon ratification, with no scheduled increase during the term
of this Agreement.

Article 7 — Grievance Procedure
An employee grievance must be filed in writing within 45 calendar days
of the incident giving rise to the grievance. The Employer shall respond
within 15 business days of filing.

Article 9 — Overtime
Overtime shall be paid at 1.5x the base rate for hours worked beyond 40
in a scheduled workweek, subject to Employer approval prior to the shift.
"""

UNION_POSITION = """LOCAL 214 — BARGAINING POSITION MEMO

Wages (Article 3): Membership rejects the proposed $24.00/hour base rate
for Grade II. Our position is $28.00/hour effective upon ratification,
with a $1.00/hour step increase in year two, given comparable Grade II
rates at three nearby unionized facilities are already above $26/hour.

Grievance Procedure (Article 7): The 45-day filing window is too long and
disadvantages members who may not immediately recognize a violation. We
propose a 30-day filing window, matching our prior agreement's terms.

Overtime (Article 9): No objection to the 1.5x rate or the 40-hour
threshold. We do object to requiring prior Employer approval before an
overtime shift — this has been used to deny legitimately earned overtime
after the fact. Propose striking the approval requirement.
"""

EMPLOYER_POSITION = """NORTHFIELD MANUFACTURING — BARGAINING POSITION MEMO

Wages (Article 3): $24.00/hour reflects current market conditions and
budget constraints for this fiscal year. We are open to discussing a
modest increase in year two of the agreement, contingent on production
targets, but cannot commit to $28.00/hour at ratification.

Grievance Procedure (Article 7): The 45-day window as drafted is
acceptable and unchanged from our position; we have no counter-proposal
here and consider Article 7 as drafted to reflect our position already.

Overtime (Article 9): Prior approval for overtime is a scheduling and
budget-control necessity for the Employer and is not open for
negotiation. The 1.5x rate and 40-hour threshold are acceptable as
drafted.
"""

FILES = {
    "cba-draft.txt": CBA_DRAFT,
    "union-position.txt": UNION_POSITION,
    "employer-position.txt": EMPLOYER_POSITION,
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in FILES.items():
        (OUTPUT_DIR / name).write_text(content)
    print(f"✓ seeded {len(FILES)} synthetic documents into {OUTPUT_DIR}")
    print("  wages: union $28/hr vs employer $24/hr — genuinely open")
    print("  grievance window: union wants 30 days, employer silent/accepts 45 — open")
    print("  overtime rate/threshold: both sides agree — should reconcile cleanly")
    print("  overtime approval clause: union wants it struck, employer wants it kept — open")


if __name__ == "__main__":
    main()
