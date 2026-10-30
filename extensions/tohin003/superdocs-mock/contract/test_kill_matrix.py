"""The kill matrix, guarded.

Two cheap assertions rather than a full run: the matrix takes about seventy seconds, which
belongs in CI rather than in every `pytest` invocation. What runs here is the part that
rots -- the committed matrix falling out of step with the mutants, or a mutant losing its
documentation.

The full run is `python scripts/run_kill_matrix.py --check`, wired into CI in Phase 6.
"""

from __future__ import annotations

import re
from pathlib import Path

from sdmock.mutants import REGISTRY

ROOT = Path(__file__).resolve().parent.parent
MATRIX = ROOT / "docs" / "kill-matrix.md"


def test_every_mutant_is_documented():
    """A defect nobody can read about is a trick, not evidence."""
    for mutant in REGISTRY.values():
        assert mutant.breaks, f"{mutant.id} names no behaviour it breaks"
        assert len(mutant.summary) > 20, f"{mutant.id} has no usable summary"
        assert len(mutant.why_it_matters) > 60, (
            f"{mutant.id} does not explain why the defect would matter to anyone"
        )


def test_every_mutant_breaks_a_real_ledger_row():
    ledger = (ROOT / "docs" / "behaviours.md").read_text(encoding="utf-8")
    known = set(re.findall(r"^\|\s*(B-\d{3})\s*\|", ledger, flags=re.M))
    for mutant in REGISTRY.values():
        for bid in mutant.breaks:
            assert bid in known, f"{mutant.id} cites {bid}, which is not in the ledger"


def test_the_committed_matrix_covers_every_mutant():
    """A stale matrix is worse than none: it claims coverage that may have lapsed."""
    assert MATRIX.exists(), "no kill matrix committed; run scripts/run_kill_matrix.py"
    text = MATRIX.read_text(encoding="utf-8")
    for mutant in REGISTRY.values():
        assert f"`{mutant.id}`" in text, (
            f"{mutant.id} is missing from the committed matrix -- re-run "
            "scripts/run_kill_matrix.py"
        )
    assert "SURVIVED" not in text, (
        "the committed matrix records a surviving mutant: a documented behaviour that "
        "nothing asserts. Write the missing test."
    )


def test_mutations_are_off_unless_asked_for():
    """The mock must be faithful by default; mutation is strictly opt-in."""
    from sdmock import mutants

    import os

    assert os.environ.get(mutants.MUTANT_ENV) in (None, ""), (
        "SDMOCK_MUTANT is set during a normal test run"
    )
    assert mutants.active() is None


def test_the_scenario_catalogue_is_not_stale():
    """The catalogue is generated from the cassettes, so it cannot quietly disagree.

    A hand-maintained catalogue is a second source of truth that starts drifting the
    first time a scenario is re-recorded, and drifts silently because nothing checks it.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_catalogue.py"), "--check"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout + result.stderr
