"""Adversarial audit of the TypeScript implementation.

The same twelve mutations as the Python audit. If the second implementation
catches the same class of bug, it is genuinely constrained by the specification
rather than merely shaped like its sibling.

    make audit-ts        # or: python3 mutation_audit.py

NOTE: this rewrites files under typescript/src in place while it runs, restoring them
afterwards (and on interrupt). Do not edit the tree while it is running — a
concurrent edit will produce nonsense results.
"""
import atexit, shutil, signal, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "typescript" / "src"
MUTATIONS = [
    ("runner.ts", "if (existing.state === SUCCEEDED) return existing.result;",
     "if (false) return existing.result;", "N1: stop replaying completed keys"),
    ("runner.ts", "if (onUnknown === UnknownPolicy.REFUSE) {",
     "if (false) {", "N2: stop refusing unknown outcomes by default"),
    ("runner.ts", "if (!options.naturallyIdempotent) {",
     "if (false) {", "R12: let RETRY_ANYWAY fire without the caller vouching"),
    ("runner.ts", "sent: error?.sent === undefined ? true : Boolean(error.sent),",
     "sent: error?.sent === undefined ? false : Boolean(error.sent),",
     "fail-open: assume unattested failures were never sent"),
    ("runner.ts", 'if (rule.outcome === "terminal") {',
     "if (false) {", "N5: treat terminal failures as retryable"),
    ("runner.ts", "if (verdict === Verdict.APPLIED) {",
     "if (verdict !== Verdict.INCONCLUSIVE) {", "N3: treat NOT_APPLIED as success too"),
    ("runner.ts", "for (let attempt = spent; attempt < budget; attempt++) {",
     "for (let attempt = 0; attempt < budget; attempt++) {",
     "R10: reset the retry budget on every unknown resolution (the fuzzer bug)"),
    ("store.ts", 'this.db.exec("BEGIN IMMEDIATE");',
     'this.db.exec("BEGIN DEFERRED");', "R5: weaken the atomic claim"),
    ("store.ts", "release(key: string): void {",
     "release(key: string): void {\n    return;", "R10: never release an exhausted key"),
    ("policy.ts", "for (const [when, rule] of this.rules) {",
     "for (const [when, rule] of [...this.rules].reverse()) {",
     "R6: evaluate the table bottom-up"),
    ("policy.ts", "return random() * this.ceilingMs(attempt);",
     "return this.ceilingMs(attempt);", "R11: drop the jitter"),
    ("policy.ts", 'if (r.outcome !== "success" && !r.why) {',
     "if (false) {", "loader: stop requiring a documented reason per rule"),
]

backup = Path(tempfile.mkdtemp()) / "src"
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
        print(f"  \033[35mSKIP\033[0m    {label} (anchor not found)")
        continue
    f.write_text(original.replace(old, new, 1))
    r = subprocess.run(
        ["node", "--test", "--experimental-strip-types", "--no-warnings", "tests/*.test.ts"],
        cwd=str(ROOT / "typescript"), capture_output=True, text=True, timeout=300)
    f.write_text(original)
    fails = [l for l in r.stdout.splitlines() if l.startswith("ℹ fail")]
    detail = fails[0] if fails else "no result"
    if r.returncode != 0:
        caught += 1
        print(f"  \033[32mCAUGHT\033[0m  {label}  ({detail})")
    else:
        missed += 1
        print(f"  \033[31mMISSED\033[0m  {label}  — suite stayed green")

total = caught + missed
print(f"\n  TypeScript: {caught}/{total} caught" + (f", \033[31m{missed} MISSED\033[0m" if missed else ""))
