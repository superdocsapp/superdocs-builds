"""Adversarial audit of the Python implementation.

A green test suite proves nothing on its own. This injects twelve plausible
bugs into the real source, one at a time, and reports which ones the suite
notices. Anything it misses is a gap in the tests, not a pass mark.

    make audit-py        # or: python3 scripts/mutation_audit.py

Every mutation here is one a real person would write. Four of them found real
gaps the first time this ran; see README section 9.

NOTE: this rewrites files under python/idem in place while it runs, restoring them
afterwards (and on interrupt). Do not edit the tree while it is running — a
concurrent edit will produce nonsense results.
"""
import atexit, shutil, signal, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "python" / "idem"
MUTATIONS = [
    ("runner.py", "if existing.state == SUCCEEDED:\n            return existing.result",
     "if False:\n            return existing.result",
     "N1: stop replaying completed keys (re-execute every time)"),

    ("runner.py", 'if on_unknown is UnknownPolicy.REFUSE:\n            raise OutcomeUnknown(',
     'if False:\n            raise OutcomeUnknown(',
     "N2: stop refusing unknown outcomes by default"),

    ("runner.py", "if not naturally_idempotent:",
     "if False:",
     "R12: let RETRY_ANYWAY fire without the caller vouching"),

    ("runner.py", "sent = bool(getattr(exc, \"sent\", True))",
     "sent = bool(getattr(exc, \"sent\", False))",
     "fail-open: assume unattested failures were never sent"),

    ("runner.py", "if rule.outcome == TERMINAL:",
     "if False:",
     "N5: treat terminal failures as retryable"),

    ("runner.py", "if verdict is Verdict.APPLIED:\n            self.store.succeed",
     "if verdict is not Verdict.INCONCLUSIVE:\n            self.store.succeed",
     "N3: treat NOT_APPLIED as success too"),

    ("runner.py", 'raise OutcomeUnknown(f"{detail}; reconciliation was inconclusive")',
     "pass",
     "N3: let an inconclusive reconciliation fall through to a retry"),

    ("store.py", 'conn.execute("BEGIN IMMEDIATE")',
     'conn.execute("BEGIN DEFERRED")',
     "R5: weaken the atomic claim to a deferred transaction"),

    ("store.py", "def release(self, key: str) -> None:",
     "def release(self, key: str) -> None:\n        return  # never release",
     "R10: never release an exhausted key"),

    ("policy.py", "for when, rule in self._rules:\n            if self._matches(",
     "for when, rule in reversed(self._rules):\n            if self._matches(",
     "R6: evaluate the table bottom-up (catch-all wins everything)"),

    ("policy.py", "return rng.uniform(0.0, self.ceiling_ms(attempt))",
     "return self.ceiling_ms(attempt)",
     "R11: drop the jitter, use the full ceiling every time"),

    ("policy.py", 'if r["outcome"] != "success" and not r.get("why"):',
     "if False:",
     "loader: stop requiring a documented reason for every rule"),
]

backup = Path(tempfile.mkdtemp()) / "idem"
shutil.copytree(SRC, backup)

caught = missed = 0


def restore(*_args):
    """Always put the source back. Without this, interrupting the audit leaves
    a deliberately broken file on disk — the worst possible failure mode for a
    tool whose whole job is to break things on purpose."""
    if SRC.exists():
        shutil.rmtree(SRC)
    shutil.copytree(backup, SRC)


atexit.register(restore)
signal.signal(signal.SIGINT, lambda *a: sys.exit(130))
signal.signal(signal.SIGTERM, lambda *a: sys.exit(143))

for fname, old, new, label in MUTATIONS:
    f = SRC / fname
    original = f.read_text()
    if old not in original:
        print(f"  \033[35mSKIP\033[0m  {label}\n        (anchor not found in {fname})")
        continue
    f.write_text(original.replace(old, new, 1))
    r = subprocess.run([str(ROOT / ".venv/bin/python"), "-m", "pytest", "-q", "--no-header", "-x"],
                       cwd=str(ROOT / "python"), capture_output=True, text=True)
    f.write_text(original)
    line = [l for l in r.stdout.splitlines() if "passed" in l or "failed" in l or "error" in l]
    detail = line[-1] if line else "no result"
    if r.returncode != 0:
        caught += 1
        print(f"  \033[32mCAUGHT\033[0m  {label}\n          {detail}")
    else:
        missed += 1
        print(f"  \033[31mMISSED\033[0m  {label}\n          suite stayed green — this is a real gap")

total = caught + missed
print(f"\n  {caught}/{total} mutations caught" + (f", \033[31m{missed} MISSED\033[0m" if missed else ""))
