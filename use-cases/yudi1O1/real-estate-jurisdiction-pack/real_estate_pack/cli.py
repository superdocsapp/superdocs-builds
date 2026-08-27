"""Command line for the jurisdiction pack.

Five subcommands, and four of them never touch the network:

    check       validate a lease record against a jurisdiction        offline
    facts       list the facts this jurisdiction needs answered       offline
    compare     same property across jurisdictions, side by side      offline
    preview     render the three documents to HTML                    offline
    draft       lay the pack onto a customer template via SuperDocs   live

Being strict is free because the gate is entirely offline: a record that would
produce a non-compliant pack is refused without spending an operation.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .assemble import DOCUMENT_ORDER, assemble, check_consistency
from .conditions import ConditionError
from .facts import FactView
from .io_yaml import InputError, load_request
from .models import safe_slug
from .rules import RuleFileError, available_jurisdictions, load_ruleset
from .validate import validate_pack


def _configure_stdout() -> None:
    """Windows consoles default to a legacy codepage, and SuperDocs responses are
    emoji-capable. The sibling build died on exactly this after a successful
    export — the document was fine and only the summary print crashed."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _load(args) -> tuple:
    req = load_request(args.input)
    code = getattr(args, "jurisdiction", None) or req.jurisdiction
    jurisdiction = load_ruleset(code, args.rules_dir)
    return req, jurisdiction


def _today(args) -> date:
    """`--today` exists so the staleness gate is demonstrable and testable
    without waiting for a calendar. It never changes what is written into a
    document — only which rules are considered current."""
    if getattr(args, "today", None):
        return date.fromisoformat(args.today)
    return date.today()


def _print_findings(result) -> None:
    for finding in result.blocking:
        print(f"  BLOCKING [{finding.location}] {finding.message}")
    for finding in result.warnings:
        print(f"  warning  [{finding.location}] {finding.message}")


def cmd_jurisdictions(args) -> int:
    codes = available_jurisdictions(args.rules_dir)
    if not codes:
        print(f"No jurisdiction files found in {args.rules_dir}.")
        return 1
    print(f"Jurisdictions available in {args.rules_dir}:")
    for code in codes:
        jurisdiction = load_ruleset(code, args.rules_dir)
        counts = (
            f"{len(jurisdiction.disclosures())} disclosure(s), "
            f"{len(jurisdiction.lease_clauses())} lease clause(s), "
            f"{len(jurisdiction.limits())} limit(s)"
        )
        print(f"  {code:<8} {jurisdiction.name:<24} {counts}")
    return 0


def cmd_facts(args) -> int:
    """List every fact this jurisdiction could ask about, once each, with the
    rules that depend on it. Grouped by fact rather than by rule, because the
    user's task is 'what do I still have to answer', not 'what does each rule
    want' — the same fact is often wanted by several rules."""
    from .models import UNSET

    req, jurisdiction = _load(args)
    view = FactView(req)

    needed_by: dict[str, list[str]] = {}
    for rule in jurisdiction.rules:
        for name in rule.required_facts():
            needed_by.setdefault(name, []).append(rule.title)

    print(f"Facts referenced by {jurisdiction.name} ({jurisdiction.code}) rules for "
          f"{req.property.full_address()}:\n")
    if not needed_by:
        print("  This jurisdiction's rules ask about nothing beyond the lease record itself.")
        return 0

    missing = []
    for name in sorted(needed_by):
        value = view.lookup_fact(name)
        if value is UNSET:
            state, marker = "NOT SUPPLIED", "!"
            missing.append(name)
        elif view.is_derived(name):
            state, marker = f"{value}  (derived)", " "
        else:
            state, marker = str(value), " "
        rules_wanting = needed_by[name]
        print(f" {marker} {name:<34} {state}")
        for title in rules_wanting:
            print(f"   {'':<35} needed by: {title}")

    if not missing:
        print("\nEvery fact this jurisdiction asks about has an answer.")
    else:
        print(f"\n{len(missing)} fact(s) marked ! must be answered under 'disclosure_facts' before a "
              f"pack can be assembled:")
        print("  " + ", ".join(missing))
        print("An unanswered applicability question is never read as 'does not apply'.")
    return 0


def cmd_check(args) -> int:
    req, jurisdiction = _load(args)
    today = _today(args)
    result = validate_pack(
        req, jurisdiction, today=today, allow_stale=args.allow_stale,
        small_landlord_exception=args.small_landlord_exception,
    )

    applicable = result.applicable()
    print(f"Pack {req.pack_id} — {req.property.full_address()}")
    print(f"Jurisdiction: {jurisdiction.name} ({jurisdiction.code})   evaluated as of {today.isoformat()}")
    print(f"Rules evaluated: {len(result.decisions)}   firing: {len(applicable)}")
    for rule in applicable:
        print(f"  + [{rule.kind}] {rule.title}  ({rule.citation.authority})")
    print()
    _print_findings(result)

    if not result.ok_to_draft:
        print(f"\nREFUSING TO DRAFT: {len(result.blocking)} blocking finding(s). No API call was made "
              f"and no operation was spent.")
        return 2
    print(f"\nOK to draft. {len(result.warnings)} warning(s).")
    return 0


def cmd_compare(args) -> int:
    """Run one property through several jurisdictions and print the difference.

    This is the command that makes the card's premise checkable in a few
    seconds: identical facts, four rulesets, four genuinely different outcomes.
    """
    req = load_request(args.input)
    codes = [c.strip().upper() for c in args.jurisdictions.split(",") if c.strip()]
    today = _today(args)

    rows = []
    for code in codes:
        jurisdiction = load_ruleset(code, args.rules_dir)
        result = validate_pack(
            req, jurisdiction, today=today, allow_stale=True,
            small_landlord_exception=args.small_landlord_exception,
        )
        rows.append((code, jurisdiction, result))

    print(f"Property: {req.property.full_address()}")
    print(f"Rent {req.tenancy.monthly_rent:,.2f} / deposit {req.tenancy.security_deposit:,.2f} "
          f"/ built {req.property.year_built}   evaluated as of {today.isoformat()}")
    # Comparison deliberately looks past staleness so the table shows what each
    # jurisdiction REQUIRES rather than which rulesets happen to be due a review.
    # Said out loud, because a silent override is the kind of thing that quietly
    # becomes a false claim.
    print("Stale rules are included here so the comparison is complete; run `check` "
          "for the staleness gate.\n")

    print(f"{'Jurisdiction':<12}{'Disclosures':>12}{'Clauses':>9}{'Blocking':>10}   Deposit verdict")
    print("-" * 78)
    for code, jurisdiction, result in rows:
        disclosure_n = sum(1 for d in result.decisions if d.applies and d.rule.kind == "disclosure")
        clause_n = sum(1 for d in result.decisions if d.applies and d.rule.kind == "lease_clause")
        deposit_problem = next(
            (f for f in result.blocking if f.location.endswith("security_deposit")), None
        )
        verdict = "OVER CAP — blocked" if deposit_problem else "within limits"
        print(f"{code:<12}{disclosure_n:>12}{clause_n:>9}{len(result.blocking):>10}   {verdict}")

    print("\nDisclosures required, by jurisdiction:")
    for code, jurisdiction, result in rows:
        titles = [d.rule.title for d in result.decisions if d.applies and d.rule.kind == "disclosure"]
        print(f"\n  {code} ({jurisdiction.name}):")
        for title in titles:
            print(f"    - {title}")
        undetermined = result.missing_facts()
        if undetermined:
            print(f"    (unanswered, would block: {', '.join(undetermined)})")

    unique = {}
    for code, _, result in rows:
        for decision in result.decisions:
            if decision.applies and decision.rule.kind == "disclosure":
                unique.setdefault(decision.rule.title, []).append(code)
    only_one = {title: codes_ for title, codes_ in unique.items() if len(codes_) == 1}
    if only_one:
        print("\nRequired in exactly one of these jurisdictions:")
        for title, codes_ in sorted(only_one.items()):
            print(f"  - {title}  ({codes_[0]} only)")
    return 0


def cmd_preview(args) -> int:
    """Render the three documents to HTML with no API key and no cost."""
    req, jurisdiction = _load(args)
    today = _today(args)
    result = validate_pack(
        req, jurisdiction, today=today, allow_stale=args.allow_stale,
        small_landlord_exception=args.small_landlord_exception,
    )
    if not result.ok_to_draft:
        print(f"Refusing to assemble {req.pack_id}: {len(result.blocking)} blocking finding(s).")
        _print_findings(result)
        return 2

    doc_set = assemble(req, jurisdiction, result, today=today)
    problems = check_consistency(doc_set)
    if problems:
        print("Pack is internally inconsistent — not written:")
        for problem in problems:
            print(f"  - {problem}")
        return 3

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for document in doc_set.documents:
        path = out_dir / f"{safe_slug(req.pack_id)}-{document.kind}.html"
        path.write_text(
            f"<!doctype html><meta charset='utf-8'><title>{document.title}</title>"
            f"<style>body{{font-family:Georgia,serif;max-width:46em;margin:3em auto;line-height:1.5}}"
            f"table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccc;padding:.4em;"
            f"text-align:left;vertical-align:top}}.statutory-verbatim{{border-left:4px solid #333;"
            f"padding-left:1em;background:#f7f7f7}}.unverified{{color:#b00}}.citation{{color:#555}}</style>"
            f"{document.content_html}",
            encoding="utf-8",
        )
        print(f"  wrote {path}")

    print(f"\nPack {req.pack_id}: {len(doc_set.disclosure_ids())} disclosure(s) "
          f"{doc_set.disclosure_ids()}, {len(doc_set.clause_ids())} clause(s) {doc_set.clause_ids()}")
    print("Cross-document consistency: OK")
    if result.warnings:
        print()
        _print_findings(result)
    return 0


def cmd_draft(args) -> int:
    from .client import SuperDocsClient
    from .ledger import RunLedger
    from .workflow import approve_all, draft_pack

    req, jurisdiction = _load(args)
    today = _today(args)
    result = validate_pack(
        req, jurisdiction, today=today, allow_stale=args.allow_stale,
        small_landlord_exception=args.small_landlord_exception,
    )
    if not result.ok_to_draft:
        print(f"Refusing to draft {req.pack_id}: {len(result.blocking)} blocking finding(s). "
              f"No API call made, no operation spent.")
        _print_findings(result)
        return 2

    doc_set = assemble(req, jurisdiction, result, today=today)

    def interactive(pending: list[dict]) -> list[dict]:
        decisions = []
        for change in pending:
            print("\n--- proposed change ---")
            print(f"operation : {change.get('operation')}")
            print(f"reason    : {change.get('ai_explanation', '')[:400]}")
            print(f"old       : {str(change.get('old_html'))[:300]}")
            print(f"new       : {str(change.get('new_html'))[:300]}")
            answer = input("approve? [y/N] ").strip().lower()
            decisions.append({"change_id": change["change_id"], "approved": answer == "y"})
        return decisions

    client = SuperDocsClient()
    ledger = None if args.no_ledger else RunLedger(args.ledger_path)

    def progress(kind: str, state: str) -> None:
        print(f"  [{kind}] {state}")

    pack_result = draft_pack(
        client=client,
        doc_set=doc_set,
        template_path=args.template,
        session_id=args.session_id,
        out_dir=args.out_dir,
        export_format=args.format,
        approval_callback=approve_all if args.auto_approve else interactive,
        kinds=[args.only] if args.only else None,
        ledger=ledger,
        force=args.force,
        on_progress=progress,
    )

    print(f"\nPack {pack_result.pack_id}:")
    for document in pack_result.documents:
        if document.skipped:
            print(f"  {document.kind:<20} skipped (already drafted) -> {document.exported_path}")
            continue
        verification = document.verification
        if verification is None:
            verified = "not verified"
        elif not verification.readable:
            verified = f"verification skipped, not passed ({verification.note})"
        else:
            verified = f"{verification.checked - len(verification.missing)}/{verification.checked} facts present"
        print(f"  {document.kind:<20} -> {document.exported_path}  [{verified}, {document.attempts} attempt(s)]")

    print(f"\nReview: {pack_result.approvals['approved']} change(s) approved, "
          f"{pack_result.approvals['rejected']} rejected.")
    print(f"Cost: {pack_result.usage_summary}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    from .rules import DEFAULT_RULES_DIR

    parser = argparse.ArgumentParser(
        prog="python -m real_estate_pack",
        description="Jurisdiction-aware residential lease and disclosure packs, built on SuperDocs.",
    )
    parser.add_argument("--rules-dir", default=str(DEFAULT_RULES_DIR), help="Directory of jurisdiction YAML files.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, needs_input=True):
        if needs_input:
            p.add_argument("input", help="Lease record YAML.")
            p.add_argument("--jurisdiction", help="Override the jurisdiction in the record, e.g. US-TX.")
        p.add_argument("--today", help="Evaluate staleness as of this ISO date instead of today.")
        p.add_argument("--allow-stale", action="store_true",
                       help="Proceed past rules whose review date has passed, marking them UNVERIFIED in the index.")
        p.add_argument("--small-landlord-exception", action="store_true",
                       help="Assert the jurisdiction's small-landlord deposit exception, where one exists.")
        return p

    common(sub.add_parser("check", help="Validate a record without touching the network.")).set_defaults(func=cmd_check)
    common(sub.add_parser("facts", help="List the facts this jurisdiction needs answered.")).set_defaults(func=cmd_facts)

    p_compare = common(sub.add_parser("compare", help="Compare one property across jurisdictions."))
    p_compare.add_argument("--jurisdictions", default="US-CA,US-TX,US-NY,US-FL",
                           help="Comma-separated jurisdiction codes.")
    p_compare.set_defaults(func=cmd_compare)

    p_preview = common(sub.add_parser("preview", help="Render the three documents to HTML, offline and free."))
    p_preview.add_argument("--out-dir", default="out", help="Where to write the HTML.")
    p_preview.set_defaults(func=cmd_preview)

    p_draft = common(sub.add_parser("draft", help="Draft the pack onto a template through SuperDocs."))
    p_draft.add_argument("--template", required=True, help="The customer's own template file.")
    p_draft.add_argument("--session-id", required=True, help="Base session id; each document gets its own suffix.")
    p_draft.add_argument("--out-dir", default="out")
    p_draft.add_argument("--format", default="docx", choices=["docx", "pdf", "html", "markdown", "txt"])
    p_draft.add_argument("--only", choices=list(DOCUMENT_ORDER), help="Draft just one document of the pack.")
    p_draft.add_argument("--auto-approve", action="store_true",
                         help="Answer yes to every proposed change. For CI and demos; still goes through /approve.")
    p_draft.add_argument("--force", action="store_true", help="Redraft even if an identical draft is on record.")
    p_draft.add_argument("--no-ledger", action="store_true", help="Disable the idempotency ledger.")
    p_draft.add_argument("--ledger-path", default=".superdocs_ledger.json")
    p_draft.set_defaults(func=cmd_draft)

    p_j = sub.add_parser("jurisdictions", help="List available jurisdictions.")
    p_j.set_defaults(func=cmd_jurisdictions)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Exit codes are a CI contract, so they are explicit:

        0  ok
        1  bad input, bad configuration, or the API refused
        2  refused — the pack has blocking findings
        3  the assembled pack is internally inconsistent
        4  drafted, but the result could not be verified

    3 and 4 are separated from 1 deliberately: a build failing with 4 produced a
    document that is on disk and wrong, which needs a different response from a
    run that never started.
    """
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (InputError, RuleFileError, ConditionError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        # Imported here so the offline commands never pay for the HTTP stack.
        from .client import SuperDocsError
        from .workflow import DraftNotApplied, DraftUnverified, PackInconsistent

        if isinstance(e, PackInconsistent):
            print(f"Error: {e}", file=sys.stderr)
            return 3
        if isinstance(e, (DraftNotApplied, DraftUnverified)):
            print(f"Error: {e}", file=sys.stderr)
            return 4
        if isinstance(e, SuperDocsError):
            # A missing key or a rejected request is an ordinary operating
            # condition, not a crash. A traceback here would bury the one
            # sentence that says what to do about it.
            print(f"Error: {e}", file=sys.stderr)
            return 1
        raise


if __name__ == "__main__":
    raise SystemExit(main())
