"""The statutory financial statements builder (Task 2, card S3).

Rolls FY2025 signed statements forward to FY2026 against the trial balance and
this year's event sources, computes the entire final document skeleton here, and
drives SuperDocs with single-target chunk replacements only.

See INVARIANTS.md for the "must never" list. Nothing in this package imports
from `system/` (TASK.md hard rule, Decision 4).
"""

from __future__ import annotations

__all__ = ["REPORTING_LABEL"]

# The only place a year label is written down. Everything else derives the
# reporting year from the highest `fy<year>` column in the trial balance, so a
# FY2027 corpus needs no code change (hard rule 6).
REPORTING_LABEL = "31 March"
