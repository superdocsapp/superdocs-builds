"""CLI.

    python -m statutory                       roll forward, print the report, write the HTML
    python -m statutory --live --sample 3     drive SuperDocs for the first 3 chunks
    python -m statutory --live                the full run (one operation per chunk)

`--live` is the only mode that touches the network, and it is the only mode that
needs a key. Everything else - the roll-forward, the ties, the note tree, the
checklist, the plan - runs offline, which is why the test suite can exercise it.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from .editplan import build_plan
from .orchestrator import Orchestrator, write_artifacts
from .pipeline import DEFAULT_CONFIG, prepare
from .report import render
from .superdocs.client import SuperDocsClient
from .superdocs.decisions import DecisionLedger
from .superdocs.transport import HttpTransport, redacted_key

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="statutory", description=__doc__)
    parser.add_argument("--corpus", default=str(REPO_ROOT / "corpus"))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--out", default=str(REPO_ROOT / "var" / "statutory"))
    parser.add_argument("--live", action="store_true", help="drive SuperDocs (needs a key)")
    parser.add_argument(
        "--sample", type=int, default=None, help="only issue the first N chunk replacements"
    )
    parser.add_argument("--actor", default="K. Latha (CFO)")
    parser.add_argument("--format", default="docx", help="export format for a successful run")
    args = parser.parse_args(argv)

    rolled = prepare(Path(args.corpus), Path(args.config))
    plan = build_plan(rolled.document).sample(args.sample)
    print(render(rolled, len(plan)))

    out_dir = Path(args.out)
    for path in write_artifacts(out_dir, plan):
        print(f"wrote {path}")

    print()
    print("EDIT PLAN (one single-target chunk replacement per step, one change per job)")
    for step in plan.steps:
        print(f"  {step.describe()}")

    if not args.live:
        print()
        print(
            "offline: nothing was sent. The whole roll-forward above ran with no key and no "
            "network. Add --live to drive SuperDocs."
        )
        return 0

    # Read from .env only, never from a command line and never printed
    # (hard rule 1). `override=False` so an already-exported value wins.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass

    print()
    print(f"live run: key {redacted_key()}")
    client = SuperDocsClient(HttpTransport())
    ledger = DecisionLedger(out_dir / "decisions.jsonl")
    run_id = f"stat-{uuid.uuid4().hex[:8]}"
    orchestrator = Orchestrator(
        client, ledger, args.actor, export_formats=(args.format,), export_dir=out_dir
    )
    result = orchestrator.run(run_id, plan, "varshith-precision-FY2026-statements.html")
    print()
    for line in orchestrator.log:
        print(line)
    print()
    print(f"document {result.document_id} in session {result.session_id}")
    print(result.sentence(ledger))
    if result.reverted:
        print(result.reverted)
    if result.exported:
        print(f"exported: {', '.join(result.exported)}")
    else:
        print("no export was produced")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
