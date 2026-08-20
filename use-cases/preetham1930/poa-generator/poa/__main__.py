"""CLI. A thin one - the card says a guided intake, not a UI.

    python -m poa                                 both required drafts, offline
    python -m poa --intake intakes/healthcare.json
    python -m poa --live                          drive SuperDocs for both drafts
    python -m poa --live --sample 2               the first 2 chunks of each

`--live` is the only mode that touches the network and the only mode that needs
a key. Everything else - the intake, the clause selection, the numbering, the
cross-references, the notice check and the plan - runs offline, which is why the
test suite can exercise all of it.

The intake is non-interactive on purpose: a JSON file is what the tests drive
and what the demo drives, so there is no second, easier path into the assembler
that only the tests use.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from .assemble import assemble
from .editplan import build_plan
from .intake import load_intake
from .library import Library
from .orchestrator import Orchestrator, write_artifacts
from .report import compare, render
from .superdocs.client import PoaClient
from .superdocs.decisions import DecisionLedger
from .superdocs.transport import HttpTransport, redacted_key

APP_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_ROOT.parent.parent
# The card names two drafts and grades the comparison between them, so the
# default is both, in this order.
REQUIRED = ("durable-financial", "healthcare")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poa", description=__doc__)
    parser.add_argument("--config", default=str(APP_ROOT / "config"))
    parser.add_argument(
        "--intake",
        action="append",
        default=None,
        help="path to an intake JSON; repeatable. Default: both required drafts.",
    )
    parser.add_argument("--out", default=str(REPO_ROOT / "var" / "poa"))
    parser.add_argument("--live", action="store_true", help="drive SuperDocs (needs a key)")
    parser.add_argument(
        "--sample", type=int, default=None, help="only issue the first N chunk replacements"
    )
    parser.add_argument("--actor", default="K. Latha (reviewing paralegal)")
    parser.add_argument("--format", default="docx", help="export format for a successful run")
    args = parser.parse_args(argv)

    library = Library(Path(args.config))
    paths = [
        Path(p)
        for p in (args.intake or [str(APP_ROOT / "intakes" / f"{n}.json") for n in REQUIRED])
    ]
    out_dir = Path(args.out)

    drafts = []
    plans = []
    for path in paths:
        intake = load_intake(path, library)
        draft = assemble(intake, library)
        plan = build_plan(draft).sample(args.sample)
        drafts.append(draft)
        plans.append(plan)
        print(render(intake, draft, library, len(plan)))
        for written in write_artifacts(out_dir, plan):
            print(f"  wrote {written}")
        print()
        print("  EDIT PLAN (one single-target chunk replacement per step, one change per job)")
        for step in plan.steps:
            print(f"    {step.describe()}")
        print()

    if len(drafts) == 2:
        print(compare(drafts[0], drafts[1], library))
        print()

    if not args.live:
        print(
            "offline: nothing was sent. The intake, the clause selection, the numbering, the "
            "cross-references and the notice check all ran with no key and no network. "
            "Add --live to drive SuperDocs."
        )
        return 0

    # Read from .env only, never from a command line and never printed
    # (hard rule 1). `override=False` so an already-exported value wins.
    try:
        from dotenv import load_dotenv

        load_dotenv(REPO_ROOT / ".env", override=False)
    except ImportError:
        pass

    print(f"live run: key {redacted_key()}")
    ledger = DecisionLedger(out_dir / "decisions.jsonl")
    failed = 0
    for plan in plans:
        client = PoaClient(HttpTransport())
        run_id = f"poa-{plan.draft.intake_id}-{uuid.uuid4().hex[:6]}"
        orchestrator = Orchestrator(
            client,
            ledger,
            args.actor,
            library,
            export_formats=(args.format,),
            export_dir=out_dir,
        )
        result = orchestrator.run(run_id, plan)
        print()
        print("-" * 78)
        print(
            f"{plan.draft.intake_id}: document {result.document_id} in session {result.session_id}"
        )
        for line in orchestrator.log:
            print(line)
        print(result.sentence(ledger))
        if result.reverted:
            print(result.reverted)
        print(f"exported: {', '.join(result.exported)}" if result.exported else "no export")
        # Read, not derived. If no response carried a usage block we say so
        # rather than printing our own call count as if it were the balance.
        print(
            f"billable calls issued: {client.billable_calls}; "
            + (
                f"operations balance reported by the product: {client.usage[-1]}"
                if client.usage
                else "no response carried an operations balance, so we do not know it"
            )
        )
        failed += 0 if result.ok else 1
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
