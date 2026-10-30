"""The ledger cannot rot: CI runs the coverage gate.

A behaviour ledger that drifts out of step with the suite is worse than none -- it reads
like a guarantee and is not one. This runs `scripts/check_ledger_coverage.py` in-process
and fails on any gap in either direction: a row with no test and no written excuse, a test
citing a row that does not exist, or an excuse for a row that has since been covered.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_ledger_and_suite_agree():
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_ledger_coverage.py")],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, (
        "the behaviour ledger and the contract suite have drifted apart:\n"
        f"{result.stdout}\n{result.stderr}"
    )
