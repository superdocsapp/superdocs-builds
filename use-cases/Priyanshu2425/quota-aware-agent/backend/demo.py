#!/usr/bin/env python3
"""Run the agent. With no key it runs against a documented fake, so a reviewer
can see the behaviour without spending an operation.

    python3 backend/demo.py                     # offline, against the fake
    python3 backend/demo.py --scenario tight    # not enough allowance, it degrades
    python3 backend/demo.py --scenario broke    # no allowance, it refuses to start
    python3 backend/demo.py --live              # real API, needs SUPERDOCS_API_KEY

    --sample N    small-sample mode: run at most N steps
    --receipt     print the line items and whether they add up
    --refuse      refuse a partial run rather than deliver a subset
    --ledger F    keep the operation ledger in F, so running twice shows what
                  a rerun after a crash does NOT pay for a second time
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The offline demo answers with `tests/fake.py`, the same fake the suite uses,
# so what a reviewer watches here is what the tests assert. That lives beside
# this package rather than inside it, so the project root goes on the path --
# the alternative is a second fake, and a fake nobody wrote cannot flatter the
# code that calls it.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from quota_aware_agent.policy import Policy, WhenItDoesNotFit
from quota_aware_agent import QuotaAwareAgent, Step, SuperDocsClient
from quota_aware_agent.client import HttpTransport
from quota_aware_agent.idempotency import OperationLedger

WORK = [
    Step("figures", "Correct the revenue figures in the summary table.", 25, "critical"),
    Step("dates",   "Fix the effective dates in section 3.",             25, "high"),
    Step("terms",   "Align the defined terms with the glossary.",        25, "medium"),
    Step("footer",  "Tidy the footer and page numbering.",               25, "low"),
]

SCENARIOS = {"roomy": 500, "tight": 3, "broke": 1}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", choices=sorted(SCENARIOS), default="roomy")
    p.add_argument("--live", action="store_true", help="use the real API")
    p.add_argument("--sample", type=int, default=None, help="run at most N steps")
    # HTML content, so an HTML name. SuperDocs picks its parser from the
    # extension, so "contract.docx" holding HTML is a 400 on a live run.
    p.add_argument("--file", default="contract.html")
    p.add_argument("--receipt", action="store_true",
                   help="print the line items and whether they add up")
    p.add_argument("--refuse", action="store_true",
                   help="refuse a partial run rather than deliver a subset")
    p.add_argument("--ledger", default=None,
                   help="keep the operation ledger in this file, so a second "
                        "run sees what the first one paid for")
    a = p.parse_args(argv)

    if a.live:
        try:
            transport = HttpTransport.from_env()
        except RuntimeError as e:
            print(f"{e}\n\nOr run without --live to use the fake, which costs "
                  "nothing.", file=sys.stderr)
            return 2
        sleep = None
        if transport.using_relay:
            print(f"Running against the real API through the shared relay at "
                  f"{transport.base}.\nOperations come out of its daily ration "
                  f"of {transport.daily_ration}, shared by everyone using that "
                  "key, and reset at 00:00 UTC.\n")
        else:
            print(f"Running against {transport.base} with your own key. "
                  "Operations will be billed to your account.\n")
    else:
        from tests.fake import FakeSuperDocs
        transport = FakeSuperDocs(remaining=SCENARIOS[a.scenario])
        sleep = lambda s: None
        print(f"Offline demo, scenario '{a.scenario}': "
              f"{SCENARIOS[a.scenario]} operation(s) of allowance. Nothing is billed.\n")

    client = SuperDocsClient(transport, **({"sleep": sleep} if sleep else {}))
    policy = Policy(
        reserve=1, max_steps=a.sample,
        when_it_does_not_fit=(WhenItDoesNotFit.REFUSE if a.refuse
                              else WhenItDoesNotFit.DEGRADE),
    )
    agent = QuotaAwareAgent(client, policy=policy,
                            ledger=OperationLedger(a.ledger) if a.ledger else None)

    content = b"<h1>Quarterly report</h1><p>...</p>"
    report = agent.run("demo-session", a.file, content, WORK)

    print(report.plain_language())
    print()
    print(f"  planned:   {report.planned or '-'}")
    print(f"  completed: {report.completed or '-'}")
    print(f"  deferred:  {report.deferred or '-'}")
    print(f"  stopped:   {report.stop_reason.value}")
    if a.receipt:
        print()
        print(report.receipt.render_text(report.balance_at_start,
                                         report.balance_at_end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
