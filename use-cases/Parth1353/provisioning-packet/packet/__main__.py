"""Command line.

Five verbs, each one a thing a service delivery manager actually does:

    packet build    an order arrived — assemble both packs
    packet change   something moved — propagate it, reviewing each edit
    packet verify   prove the pack says what the order says
    packet export   produce the files you will actually send
    packet audit    check the templates before you trust them (no API key needed)

Every command that spends operations supports ``--dry-run``, which prints the
exact plan and the operation cost without making a single billable call.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from packet.build import AUDIENCES, Workspace, build_all, export_pack, session_id_for
from packet.order import BY_PATH, Order, OrderError
from packet.propagate import (
    auto_approve,
    diff_orders,
    make_terminal_reviewer,
    plan,
    propagate,
)
from packet.superdocs import BudgetExceeded, Ledger, SuperDocs, SuperDocsError
from packet.templates import DOCUMENTS, audit_audience, documents_carrying, unknown_fields
from packet.verify import (
    live_text,
    load_snapshot,
    reset_body_cache,
    save_snapshot,
    snapshot,
    verify_audience,
    verify_diagram,
    verify_propagation,
)

DEFAULT_ORDER = "orders/acme-fiber-SO-40188.yaml"
DEFAULT_OUT = "out"


def _load_env() -> None:
    """Read a .env if present. No dependency, no surprises."""
    for candidate in (Path(".env"), Path(__file__).resolve().parent.parent / ".env"):
        if not candidate.exists():
            continue
        for line in candidate.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return


def _client(args) -> SuperDocs:
    _load_env()
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    ledger = Ledger(limit=args.max_operations, dry_run=getattr(args, "dry_run", False))
    if ledger.dry_run and not key:
        # A dry run makes no calls, so it must not require a key — that is the
        # whole point of being able to cost a change before committing to it.
        key = "sk_dry_run_placeholder"
    return SuperDocs(key, ledger=ledger)


def _say(*parts) -> None:
    print(*parts, flush=True)


def _rule(title: str) -> None:
    print(f"\n\033[1m{title}\033[0m", flush=True)


# ---------------------------------------------------------------------------


def cmd_audit(args) -> int:
    """Offline. Checks the templates against the registry before anything is built."""
    _rule("Templates")
    for spec in DOCUMENTS:
        internal_only = len(spec.fields) - len(spec.customer_fields)
        diag = " · diagram" if spec.has_diagram else ""
        _say(
            f"  {spec.slug:<34} {len(spec.fields):>2} fields "
            f"({len(spec.customer_fields)} customer-visible, {internal_only} internal){diag}"
        )

    _rule("Audience safety")
    leaks = audit_audience()
    unknown = unknown_fields()
    if leaks:
        for line in leaks:
            _say(f"  FAIL  {line}")
    else:
        _say("  PASS  no internal field can reach a customer render")
    if unknown:
        for line in unknown:
            _say(f"  FAIL  {line}")
    else:
        _say("  PASS  every placeholder resolves to a declared field")

    _rule("Change impact")
    for path in args.impact or [
        "delivery.rfs_date",
        "service.bandwidth_mbps",
        "commercial.mrc",
    ]:
        if path not in BY_PATH:
            _say(f"  {path}: not a declared field")
            continue
        internal = documents_carrying(path, audience="internal")
        customer = documents_carrying(path, audience="customer")
        _say(f"  {path} ({BY_PATH[path].label})")
        _say(f"    internal pack: {len(internal)}/6 — {', '.join(d.slug for d in internal) or 'none'}")
        _say(f"    customer pack: {len(customer)}/6 — {', '.join(d.slug for d in customer) or 'none'}")

    return 1 if (leaks or unknown) else 0


def cmd_build(args) -> int:
    order = Order.load(args.order)
    workspace = Workspace(args.out)
    audiences = tuple(args.audience) if args.audience else AUDIENCES

    _rule(f"Building {order.value('order.reference')} — {order.value('customer.legal_name')}")
    _say(f"  order record  {order.source} (fingerprint {order.fingerprint()})")
    _say(f"  packs         {', '.join(audiences)}")
    _say(f"  documents     {len(args.only or DOCUMENTS)} per pack")
    _say(f"  sessions      {', '.join(session_id_for(order, a) for a in audiences)}")

    with _client(args) as client:
        if args.dry_run:
            _say("\n  DRY RUN — no call will be made and nothing will be billed.")
        else:
            _report_quota(client)

        try:
            packs = build_all(
                client, order, workspace=workspace, audiences=audiences, only=args.only
            )
        except BudgetExceeded as exc:
            _say(f"\n  stopped: {exc}")
            return 2

        _rule("Built")
        for audience, pack in packs.items():
            for doc in pack.documents:
                chunks = f"{doc.chunk_count} chunks" if doc.chunk_count else "uploaded"
                _say(f"  {audience:<9} {doc.slug:<34} {chunks}")

        if not args.dry_run:
            save_snapshot(workspace, snapshot(client, packs))

        _rule("Cost")
        _say("  " + json.dumps(client.ledger.summary()))
        _say(f"\n  manifest: {workspace.manifest_path}")
        _say(f"  html:     {workspace.root}/<audience>/")
    return 0


def cmd_change(args) -> int:
    before = Order.load(args.order)
    after = before.copy()

    for assignment in args.set or []:
        if "=" not in assignment:
            raise OrderError(f"--set expects path=value, got {assignment!r}")
        path, raw = assignment.split("=", 1)
        after.set(path.strip(), _coerce(raw.strip()))
    if args.to:
        after = Order.load(args.to)
    after.validate()

    changes = diff_orders(before, after)
    if not changes:
        _say("  nothing changed — no edit would be honest")
        return 1

    workspace = Workspace(args.out)
    packs = workspace.load()

    _rule("Change")
    for c in changes:
        _say(f"  {c.label}: {c.before_text}  →  {c.after_text}")

    planned, untouched = plan(changes, packs, before=before, after=after)
    _rule(f"Plan — {len(planned)} document(s) to edit, {len(untouched)} left alone")
    for edit in planned:
        why = ", ".join(c.label for c in edit.changes) or "diagram only"
        diag = " + regenerate diagram" if edit.regenerate_diagram else ""
        _say(f"  EDIT  {edit.audience}/{edit.slug:<34} {why}{diag}")
    for key in untouched:
        _say(f"  KEEP  {key}")

    if args.dry_run:
        _rule("Dry run")
        _say(f"  {len(planned)} billable operation(s) would be spent, one per document.")
        _say("  Nothing was sent. Re-run without --dry-run to apply.")
        if args.show_instruction and planned:
            _rule(f"Instruction that would be sent to {planned[0].slug}")
            _say(planned[0].instruction)
        return 0

    if len(planned) > args.max_operations:
        _say(
            f"\n  refusing: the plan needs {len(planned)} operations and the budget is "
            f"{args.max_operations}. Raise --max-operations or narrow the change."
        )
        return 2

    reviewer = auto_approve if args.yes else make_terminal_reviewer()
    if args.yes:
        _say("\n  --yes: every proposed change will be approved without review.")

    with _client(args) as client:
        _report_quota(client)
        before_snap = load_snapshot(workspace) or snapshot(client, packs)

        report = propagate(
            client,
            before=before,
            after=after,
            packs=packs,
            review=reviewer,
            model_tier=args.model_tier,
            on_progress=lambda who, msg: _say(f"    {who}: {msg}") if args.verbose else None,
        )

        _rule("Applied")
        for o in report.outcomes + report.repairs:
            if o.error:
                _say(f"  FAIL  {o.audience}/{o.slug}: {o.error}")
            elif o.skipped_reason:
                _say(f"  SKIP  {o.audience}/{o.slug}: {o.skipped_reason}")
            else:
                _say(f"  OK    {o.audience}/{o.slug}: {o.applied} approved, {o.rejected} rejected")

        after.save(args.order if args.write_back else Path(args.out) / "order.updated.yaml")
        _say(
            f"\n  updated order record → "
            f"{args.order if args.write_back else Path(args.out) / 'order.updated.yaml'}"
        )

        _rule("Proof")
        reset_body_cache()  # the bodies changed; re-read them

        def live(pack, doc):
            return live_text(client, pack, doc)

        v = verify_propagation(
            client,
            packs=packs,
            order=after,
            changed_paths=[c.path for c in changes],
            before_snapshot=before_snap,
        )
        _say(v.render())

        # The field check can pass while the diagram is stale: a value may
        # appear in a table and not in the picture. Checked separately, against
        # the order the change was made to.
        d = verify_diagram(packs, after, fetch_text=live)
        _say(d.render())

        save_snapshot(workspace, snapshot(client, packs))
        _rule("Cost")
        _say("  " + json.dumps(client.ledger.summary()))
        return 0 if (v.passed and d.passed and not report.failed) else 1


def cmd_verify(args) -> int:
    order = Order.load(args.order)
    workspace = Workspace(args.out)
    packs = workspace.load()

    with _client(args) as client:
        # `--live` must actively supply the live reader. Passing None let the
        # verifiers fall back to their own default, which is the LOCAL render —
        # so the flag silently did the opposite of what it says and reported a
        # stale pack as correct. A flag that quietly does nothing is worse than
        # no flag at all.
        if args.live:
            reset_body_cache()

            def fetch(pack, doc):
                return live_text(client, pack, doc)

            _say("  reading the live documents from SuperDocs")
        else:

            def fetch(pack, doc):
                return Path(doc.local_path).read_text()

            _say("  reading the local renders — pass --live to check SuperDocs")

        _rule("Audience separation")
        a = verify_audience(packs, order, fetch_text=fetch)
        _say(a.render())

        _rule("Diagram fidelity")
        d = verify_diagram(packs, order, fetch_text=fetch)
        _say(d.render())

        ok = a.passed and d.passed
        if args.json:
            print(json.dumps({"audience": a.as_dict(), "diagram": d.as_dict()}, indent=2))
        return 0 if ok else 1


def cmd_export(args) -> int:
    workspace = Workspace(args.out)
    packs = workspace.load()
    with _client(args) as client:
        _rule(f"Exporting as .{args.format} (exports never cost an operation)")
        reset_body_cache()
        for audience, pack in packs.items():
            if args.audience and audience not in args.audience:
                continue
            written = export_pack(
                client, pack, workspace=workspace, fmt=args.format, live=not args.from_local
            )
            for path in written:
                _say(f"  {path}")
            for w in pack.warnings:
                _say(f"\n  WARNING [{w.get('code')}] {w.get('document', '')}")
                _say(f"    {w.get('message')}")
    return 0


def _report_quota(client: SuperDocs) -> None:
    try:
        who = client.whoami()
        used = who.get("monthly_used") or who.get("operations_used")
        limit = who.get("monthly_limit") or who.get("operations_limit")
        if used is not None and limit is not None:
            _say(f"  account       {who.get('subscription_tier', 'unknown')} · {used}/{limit} operations used")
    except SuperDocsError:
        pass  # informational only; never block a build on it


def _coerce(raw: str):
    lowered = raw.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        "packet",
        description="Provisioning and service-order packs, built on SuperDocs.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="command", required=True)

    def common(sp, *, needs_order=True):
        if needs_order:
            sp.add_argument("--order", default=DEFAULT_ORDER, help="the order record (YAML)")
        sp.add_argument("--out", default=DEFAULT_OUT, help="workspace directory")
        sp.add_argument("--max-operations", type=int, default=40,
                        help="stopping rule: refuse to spend more than this")
        sp.add_argument("--dry-run", action="store_true",
                        help="print the plan and its cost without making a billable call")

    a = sub.add_parser("audit", help="check the templates offline — no API key needed")
    a.add_argument("--impact", action="append",
                   help="show which documents a change to this field would touch")
    a.set_defaults(fn=cmd_audit, max_operations=0, dry_run=True)

    b = sub.add_parser("build", help="assemble both packs from an order record")
    common(b)
    b.add_argument("--audience", action="append", choices=list(AUDIENCES))
    b.add_argument("--only", action="append", help="build only these document slugs")
    b.set_defaults(fn=cmd_build)

    c = sub.add_parser("change", help="propagate a change through every document that carries it")
    common(c)
    c.add_argument("--set", action="append", metavar="path=value")
    c.add_argument("--to", help="a second order record to diff against instead of --set")
    c.add_argument("--yes", action="store_true", help="approve every proposed change unreviewed")
    c.add_argument("--write-back", action="store_true",
                   help="save the new values over the original order record")
    c.add_argument("--model-tier", default="pro", choices=["core", "turbo", "pro", "max"])
    c.add_argument("--show-instruction", action="store_true",
                   help="with --dry-run, print the exact message that would be sent")
    c.set_defaults(fn=cmd_change)

    v = sub.add_parser("verify", help="prove the packs say what the order says")
    common(v)
    v.add_argument("--live", action="store_true",
                   help="read the documents back from SuperDocs instead of local renders")
    v.add_argument("--json", action="store_true")
    v.set_defaults(fn=cmd_verify, dry_run=False)

    e = sub.add_parser("export", help="produce .docx / .pdf files")
    common(e, needs_order=False)
    e.add_argument("--format", default="docx",
                   choices=["docx", "pdf", "html", "markdown", "txt"])
    e.add_argument("--audience", action="append", choices=list(AUDIENCES))
    e.add_argument("--from-local", action="store_true",
                   help="export the originally rendered files rather than the live "
                        "documents (for comparison; never for sending)")
    e.set_defaults(fn=cmd_export)

    return p


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)-5s %(name)s: %(message)s",
    )
    try:
        return args.fn(args)
    except (OrderError, SuperDocsError) as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted — nothing further was sent", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
