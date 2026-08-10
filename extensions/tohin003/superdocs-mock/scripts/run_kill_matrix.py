#!/usr/bin/env python3
"""Boot the mock under each mutant, run the suite, and record what caught it.

This is the answer to "does your contract suite actually catch anything". Each mutant
breaks exactly one documented behaviour; the suite is run against it unchanged; a mutant
that does not produce a failure is a hole, not a curiosity.

    python scripts/run_kill_matrix.py               # run all, write docs/kill-matrix.md
    python scripts/run_kill_matrix.py M1 M6         # a subset, for iterating
    python scripts/run_kill_matrix.py --check       # fail if any mutant survives

Costs nothing and needs no key: every run is against the local mock.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from sdmock.mutants import REGISTRY  # noqa: E402

OUT = ROOT / "docs" / "kill-matrix.md"
FAILED = re.compile(r"^FAILED\s+(\S+)")

# Tests that fail whenever *any* mutant is active, because they assert the mock is not
# running one. They are worth having -- a broken mock must never pass for a faithful one
# -- but they detect the harness rather than the defect, so counting them would mean
# every mutant looked caught even if nothing behavioural noticed. Excluded from kills.
TAUTOLOGICAL = {
    "test_the_mock_is_not_secretly_running_a_mutant",
    "test_mutations_are_off_unless_asked_for",
}

# Self-referential: this test asserts the *committed* matrix is current, and this script
# is what makes it current. Letting it gate the baseline deadlocks the tool against its
# own output -- a stale matrix reddens the baseline, and the runner then refuses to run
# and regenerate it. Excluded from the baseline check only; it still runs in CI, where
# it is exactly the guard that matters.
NOT_A_BASELINE_CONCERN = {"test_the_committed_matrix_covers_every_mutant"}


def run_suite(mutant_id: str | None, transport: str) -> tuple[int, list[str], float]:
    """Run the contract suite once, returning (exit code, failing tests, seconds)."""
    env = dict(os.environ)
    if mutant_id:
        env["SDMOCK_MUTANT"] = mutant_id
    else:
        env.pop("SDMOCK_MUTANT", None)

    began = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "contract/", "-q", "-rf", "--tb=no",
         "-p", "no:cacheprovider", "--transport", transport],
        cwd=ROOT, env=env, capture_output=True, text=True,
    )
    elapsed = time.perf_counter() - began
    failures = [
        name for name in (
            FAILED.match(line).group(1).split("::")[-1]
            for line in result.stdout.splitlines() if FAILED.match(line)
        )
        if name not in TAUTOLOGICAL
    ]
    return result.returncode, failures, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mutants", nargs="*", help="mutant ids; default all")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if any mutant survives")
    args = ap.parse_args()

    chosen = [m.upper() for m in args.mutants] or list(REGISTRY)
    unknown = [m for m in chosen if m not in REGISTRY]
    if unknown:
        print(f"unknown mutant(s): {unknown}", file=sys.stderr)
        return 2

    print("baseline (no mutant) ...", end=" ", flush=True)
    for transport in ("rest", "mcp"):
        code, failures, seconds = run_suite(None, transport)
        failures = [f for f in failures if f not in NOT_A_BASELINE_CONCERN]
        if failures:
            print(f"\nthe suite is already failing on {transport} before any mutant is "
                  f"applied: {failures}", file=sys.stderr)
            print("Fix that first -- a kill matrix built on a red baseline means "
                  "nothing.", file=sys.stderr)
            return 2
    print(f"green ({seconds:.1f}s)\n")

    rows: list[dict] = []
    survivors: list[str] = []

    for mutant_id in chosen:
        mutant = REGISTRY[mutant_id]
        code, failures, seconds = run_suite(mutant_id, mutant.transport)
        # `killed` deliberately ignores the exit code and asks only whether a
        # behavioural test failed. A run can exit non-zero purely on the tautological
        # tests, and that is not a kill.
        killed = bool(failures)
        rows.append({
            "mutant": mutant,
            "killed": killed,
            "failures": failures,
            "seconds": seconds,
        })
        if not killed:
            survivors.append(mutant_id)
        status = f"killed by {len(failures)} test(s)" if killed else "SURVIVED"
        print(f"  {mutant_id:4s} {mutant.transport:4s} {status:28s} "
              f"{mutant.summary[:52]}")

    killed_count = sum(1 for r in rows if r["killed"])
    print(f"\n{killed_count}/{len(rows)} mutants killed")

    write_matrix(rows, killed_count)
    print(f"wrote {OUT.relative_to(ROOT)}")

    if survivors:
        print(f"\nSURVIVORS: {survivors}", file=sys.stderr)
        print("Each one is a documented behaviour nothing asserts. Write the missing "
              "test -- do not weaken the mutant.", file=sys.stderr)
        return 1 if args.check else 0
    return 0


def write_matrix(rows: list[dict], killed: int) -> None:
    lines = [
        "# Kill matrix",
        "",
        "*Generated by `scripts/run_kill_matrix.py`. Do not edit by hand.*",
        "",
        "A passing test suite proves nothing on its own -- it might be asserting real",
        "invariants or it might be asserting that `200 == 200`, and from the outside those",
        "look the same. So the mock is booted with one deliberate defect at a time and the",
        "suite is run against it unchanged. A mutant that survives is a documented",
        "behaviour nothing defends.",
        "",
        f"**{killed} of {len(rows)} mutants killed.**",
        "",
        "| Mutant | Breaks | Defect | Caught by |",
        "|---|---|---|---|",
    ]
    for row in rows:
        mutant = row["mutant"]
        if row["killed"]:
            caught = "<br>".join(f"`{name}`" for name in sorted(set(row["failures"]))[:4])
            extra = len(set(row["failures"])) - 4
            if extra > 0:
                caught += f"<br>*(+{extra} more)*"
        else:
            caught = "**SURVIVED — nothing caught this**"
        breaks = ", ".join(mutant.breaks)
        lines.append(f"| `{mutant.id}` | {breaks} | {mutant.summary} | {caught} |")

    lines += [
        "",
        "Tests that merely detect *that* a mutant is active -- the posture checks "
        "asserting the mock is not secretly running one -- are excluded from these "
        "counts. They fail under every mutant, so counting them would make each one "
        "look caught even when nothing behavioural noticed.",
        "",
        "## Why each defect would matter",
        "",
    ]
    for row in rows:
        mutant = row["mutant"]
        lines.append(f"**{mutant.id} — {mutant.summary}**  ")
        lines.append(f"{mutant.why_it_matters}")
        lines.append("")

    total = sum(row["seconds"] for row in rows)
    lines += [
        "---",
        "",
        f"Full matrix runs in {total:.0f}s against the local mock, with no API key and "
        "no operations spent.",
        "",
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
