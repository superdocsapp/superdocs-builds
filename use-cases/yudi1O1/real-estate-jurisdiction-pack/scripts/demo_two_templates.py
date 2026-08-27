"""Prove the pack's content is template-independent, against the live API.

The pack ships two deliberately dissimilar customer templates — a brokerage's
sans-serif house style and a law firm's serif instrument style. The claim they
exist to support is:

    The same pack drafted onto two different templates carries identical facts
    and differs only in presentation.

That claim is worth nothing unless it can fail, so this script tries to break it:
it drafts every document of a pack onto both templates and asserts that every
fact the verifier cares about — reference codes, statutory anchors, citations,
verification and review dates — appears in BOTH exports.

    python scripts/demo_two_templates.py --example examples/tx_austin_apartment.yaml

**This script spends real money.** Six billable chat operations per run (three
documents x two templates). It needs SUPERDOCS_API_KEY. Nothing else in this
project does.

**It has not been run by the author.** No key was available while this was built
— see the README's *What has and has not been exercised*. The control flow it
exercises is covered offline in tests/test_workflow.py against a fake client;
what is unproven is the live behaviour, and this script is how you would find
out. Expect the disclosure packet to be the one that needs a retry: it is the
longest and most section-heavy of the three, and partial application is the
documented failure mode for exactly that shape.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from real_estate_pack.assemble import DOCUMENT_ORDER, assemble  # noqa: E402
from real_estate_pack.client import SuperDocsClient  # noqa: E402
from real_estate_pack.io_yaml import load_request  # noqa: E402
from real_estate_pack.rules import load_ruleset  # noqa: E402
from real_estate_pack.validate import validate_pack  # noqa: E402
from real_estate_pack.verify import expected_facts, verify_export  # noqa: E402
from real_estate_pack.workflow import approve_all, draft_pack  # noqa: E402

TEMPLATES = {
    "brokerage": "templates/brokerage_template.html",
    "law_firm": "templates/law_firm_template.html",
}


def _configure_stdout() -> None:
    """Line-buffer stdout and force UTF-8.

    Both matter here and were found by running this for real. Python
    block-buffers stdout when it is piped rather than attached to a terminal, so
    redirecting this script to a log file showed *nothing at all* for the ten
    minutes it was spending the user's money — the run looked hung when it was
    working fine. And a Windows console defaults to a legacy codepage that
    cannot encode the em-dashes and section signs in these citations, which
    killed the sibling build's CLI after a successful export.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        except (AttributeError, ValueError):
            pass


def facts_absent(export_path: str, doc_set, kind: str) -> list[str]:
    """Which expected facts are missing from this export. Uses the same public
    verifier the workflow uses, so this script cannot accidentally hold the
    output to a different standard than the drafter does."""
    result = verify_export(export_path, doc_set, kind)
    if not result.readable:
        raise SystemExit(
            f"Cannot verify {export_path}: {result.note}. Re-run with --format docx or "
            f"--format markdown; PDF text extraction is out of scope."
        )
    return list(result.missing)


def main() -> int:
    _configure_stdout()
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--example", default="examples/tx_austin_apartment.yaml")
    parser.add_argument("--out-dir", default="out/parity")
    parser.add_argument("--format", default="docx")
    parser.add_argument("--allow-stale", action="store_true")
    parser.add_argument("--session-prefix", default=f"parity-{int(time.time())}")
    args = parser.parse_args()

    if not os.environ.get("SUPERDOCS_API_KEY"):
        print("SUPERDOCS_API_KEY is not set. This script is the only part of this project "
              "that needs one, and it spends 6 billable operations per run.", file=sys.stderr)
        return 1

    req = load_request(args.example)
    jurisdiction = load_ruleset(req.jurisdiction)
    validation = validate_pack(req, jurisdiction, allow_stale=args.allow_stale)
    if not validation.ok_to_draft:
        print(f"Refusing to draft: {len(validation.blocking)} blocking finding(s). "
              f"Nothing was billed.", file=sys.stderr)
        for finding in validation.blocking:
            print(f"  BLOCKING [{finding.location}] {finding.message}", file=sys.stderr)
        return 2

    doc_set = assemble(req, jurisdiction, validation)
    client = SuperDocsClient()

    print(f"Pack {req.pack_id} — {jurisdiction.name}")
    print(f"Method: every expected fact for each document must appear in BOTH exports. "
          f"Facts are derived from the pack data, never from the output text.\n")

    exports: dict[str, dict[str, str]] = {}
    for label, template in TEMPLATES.items():
        print(f"drafting onto {label} ({template}) ...")
        started = time.time()

        def progress(kind: str, state: str, _t0=started) -> None:
            # Streamed as it happens. Each document legitimately takes minutes,
            # so a run that printed only at the end was indistinguishable from a
            # hang while it spent real operations.
            print(f"  [{time.time() - _t0:6.1f}s] {kind:<20} {state}")

        result = draft_pack(
            client=client,
            doc_set=doc_set,
            template_path=template,
            session_id=f"{args.session_prefix}-{label}",
            out_dir=str(Path(args.out_dir) / label),
            export_format=args.format,
            approval_callback=approve_all,
            ledger=None,  # parity must measure fresh draws, never a cached skip
            on_progress=progress,
        )
        exports[label] = {d.kind: d.exported_path for d in result.documents}
        for document in result.documents:
            print(f"  {document.kind:<20} {document.attempts} attempt(s) -> {document.exported_path}")

    print("\nparity check")
    failures = 0
    for kind in DOCUMENT_ORDER:
        missing_by_template = {}
        for label in TEMPLATES:
            absent = facts_absent(exports[label][kind], doc_set, kind)
            if absent:
                missing_by_template[label] = absent
        total = len(expected_facts(doc_set, kind))
        if missing_by_template:
            failures += 1
            print(f"  {kind:<20} FAILED ({total} facts checked)")
            for label, absent in missing_by_template.items():
                print(f"      {label}: {len(absent)} missing — {absent[:6]}")
        else:
            print(f"  {kind:<20} parity OK ({total} facts present in both)")

    print(f"\nCost: {client.usage.summary()}")
    if failures:
        print(f"\nparity held for {len(DOCUMENT_ORDER) - failures}/{len(DOCUMENT_ORDER)} documents. "
              f"A failure here means the content is NOT template-independent — report which "
              f"facts went missing and on which template.")
        return 1
    print(f"\nparity held for all {len(DOCUMENT_ORDER)} documents. Note this is n=1: the model is "
          f"non-deterministic, so a single green run supports 'this can work', not 'this always "
          f"works'. Run it several times before treating it as a measurement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
