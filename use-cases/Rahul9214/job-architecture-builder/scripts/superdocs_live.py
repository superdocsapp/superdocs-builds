"""Manual SuperDocs live verification. Not collected by pytest.

Requires SUPERDOCS_API_KEY for mutating commands. Never prints the key.
Stops at human approval unless decide is given explicit per-change decisions.
State is saved under .runtime/ so a restart can resume without duplicating work.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from job_architecture.fixtures import PROJECT_ROOT
from job_architecture.live.job_state import annotate_review, load_and_prepare, reviewed_job_action
from job_architecture.live.domain_apply import (
    apply_verified_domain,
    record_preservation_verification,
    record_structure_verification,
)
from job_architecture.live.orchestrator import LiveIntent, LiveOrchestrator, prepare_demo_artifacts
from job_architecture.live.preservation import inspect_docx_layout, verify_exported_framework, verify_exported_profile
from job_architecture.profile_structure import validate_profile_document_text
from job_architecture.live.review import format_pending
from job_architecture.live.state import RuntimeStore
from job_architecture.live.subset import build_demo_framework, load_demo_subset
from job_architecture.superdocs.client import SuperDocsClient
from job_architecture.superdocs.config import load_settings
from job_architecture.superdocs.errors import ConfigurationError, JobFailedError, JobTimeoutError, SuperDocsError
from job_architecture.superdocs.models import ReviewDecision

DEFAULT_ARTIFACTS = PROJECT_ROOT / "artifacts" / "live"
DEFAULT_EXPORTS = PROJECT_ROOT / "exports"
DEFAULT_STATE = PROJECT_ROOT / ".runtime" / "live-state.json"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Resumable SuperDocs live verification. Does not auto-approve."
    )
    parser.add_argument(
        "command",
        choices=(
            "prepare",
            "upload",
            "framework",
            "profile",
            "repair-profile",
            "surgical-update",
            "search",
            "status",
            "decide",
            "continue",
            "export",
            "verify-export",
            "verify-profile-structure",
            "verify-framework-structure",
            "finalize-domain",
            "annotate-review",
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required for mutating SuperDocs calls in non-interactive runs.",
    )
    parser.add_argument("--job", default=None, help="Saved job name: framework, profile, profile_repair, surgical, search.")
    parser.add_argument(
        "--review-outcome",
        default=None,
        help="Local-only review annotation for annotate-review: approved, rejected, mixed, or none.",
    )
    parser.add_argument(
        "--change",
        action="append",
        default=[],
        metavar="ID:approve|reject",
        help="Explicit decision. Repeatable. No --change means display only.",
    )
    parser.add_argument("--kind", default="profile", help="Document kind for export/verify-export.")
    parser.add_argument("--path", type=Path, default=None, help="Export destination or exported DOCX to verify.")
    parser.add_argument("--artifacts", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    args = parser.parse_args(argv)

    store = RuntimeStore(args.state)

    if args.command == "prepare":
        written = prepare_demo_artifacts(args.artifacts, store)
        for name, path in written.items():
            print(f"wrote {name}: {path}")
        print("Local DOCX generation only. No SuperDocs call.")
        return 0

    if args.command in {
        "status",
        "verify-export",
        "verify-profile-structure",
        "verify-framework-structure",
        "finalize-domain",
        "annotate-review",
    }:
        return _local_command(args, store)

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(exc, file=sys.stderr)
        return 2

    with SuperDocsClient(settings) as client:
        orchestrator = LiveOrchestrator(client, store, artifacts_dir=args.artifacts)
        if args.command == "upload":
            return _run_mutating(args, orchestrator.upload_intent(), lambda: _do_upload(orchestrator))
        if args.command == "framework":
            return _run_mutating(args, orchestrator.framework_intent(), lambda: _do_job(orchestrator.start_framework, "framework"))
        if args.command == "profile":
            return _run_mutating(args, orchestrator.profile_intent(), lambda: _do_profile(orchestrator))
        if args.command == "repair-profile":
            return _run_mutating(
                args,
                orchestrator.repair_profile_intent(),
                lambda: _do_job(orchestrator.start_profile_repair, "profile_repair"),
            )
        if args.command == "surgical-update":
            return _run_mutating(
                args,
                orchestrator.surgical_intent(),
                lambda: _do_job(orchestrator.start_surgical_update, "surgical"),
            )
        if args.command == "search":
            return _run_mutating(args, orchestrator.search_intent(), lambda: _do_search(orchestrator))
        if args.command == "decide":
            job_name = args.job or _latest_review_job(orchestrator)
            if not job_name:
                print("No saved job. Run framework, profile, or surgical-update first.", file=sys.stderr)
                return 2
            snapshot = orchestrator.pending_changes(job_name)
            print(format_pending(snapshot))
            if not args.change:
                print("No decisions submitted. Pass --change ID:approve or --change ID:reject.")
                return 0
            decisions = _parse_decisions(args.change)
            intent = LiveIntent(
                action="decide",
                summary=f"Submit {len(decisions)} explicit review decision(s) for job {job_name}.",
                mutating_calls=("POST /v1/chat/{session}/approve",),
                estimated_count=1,
            )
            return _run_mutating(args, intent, lambda: _do_decide(orchestrator, job_name, decisions))
        if args.command == "continue":
            job_name = args.job or _latest_review_job(orchestrator)
            if not job_name:
                print("No saved job to continue.", file=sys.stderr)
                return 2
            return _run_mutating(
                args,
                orchestrator.continue_intent(job_name),
                lambda: _do_job(lambda: orchestrator.continue_after_review(job_name), job_name),
            )
        if args.command == "export":
            kind = args.kind
            destination = args.path or (DEFAULT_EXPORTS / f"{kind}.docx")
            try:
                intent = orchestrator.export_intent(kind)
            except SuperDocsError as exc:
                print(exc, file=sys.stderr)
                print("No SuperDocs call was made.")
                return 1
            return _run_mutating(
                args,
                intent,
                lambda: _do_export(orchestrator, kind, destination),
            )
    print(f"Unknown command {args.command}", file=sys.stderr)
    return 2


def _local_command(args, store: RuntimeStore) -> int:
    if args.command == "annotate-review":
        state = store.load()
        if state is None:
            print(f"No runtime state at {store.path}", file=sys.stderr)
            return 2
        if not args.job:
            print("--job is required for annotate-review", file=sys.stderr)
            return 2
        if not args.review_outcome:
            print("--review-outcome is required (approved, rejected, mixed, or none)", file=sys.stderr)
            return 2
        state = load_and_prepare(store)
        if state is None:
            print(f"No runtime state at {store.path}", file=sys.stderr)
            return 2
        try:
            job = annotate_review(state, args.job, args.review_outcome)
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
        store.save(state)
        print("Local review annotation only. No SuperDocs call.")
        print(
            f"{args.job}: remote_job_status={job.get('remote_job_status')} "
            f"review_outcome={job.get('review_outcome')} "
            f"mutation_applied={job.get('mutation_applied')} "
            f"domain_applied={job.get('domain_applied')}"
        )
        return 0
    if args.command == "status":
        state = load_and_prepare(store)
        if state is None:
            print(f"No runtime state at {store.path}")
            return 0
        payload = state.to_dict()
        print(f"state file: {store.path}")
        print(f"session_id: {payload['session_id']}")
        print(f"workflow:   {payload['workflow']}")
        print(f"completed:  {', '.join(payload['completed_steps']) or '(none)'}")
        print(f"documents:  {len(payload['documents'])}")
        for item in payload["documents"]:
            print(
                f"  - {item.get('role_id')} kind={item.get('kind')} "
                f"document_id={item.get('document_id')} durable={item.get('durable_document_id')}"
            )
        print(f"templates:  {list(payload['templates'])}")
        integrity = payload.get("profile_integrity") or {}
        print(
            f"profile_integrity: status={integrity.get('status') or '(none)'} "
            f"repair_required={integrity.get('repair_required')} "
            f"reason={integrity.get('reason') or '(none)'}"
        )
        verification = payload.get("verification") or {}
        structure = verification.get("structure") or {}
        preservation = verification.get("preservation") or (payload.get("preservation") or {}).get("verification") or {}
        print(
            f"verification: structure_ok={structure.get('ok')} "
            f"preservation_ok={preservation.get('ok')} "
            f"found_new_fragment={preservation.get('found_new_fragment')}"
        )
        domain = payload.get("domain_apply") or {}
        print(
            f"domain_apply: applied={domain.get('applied')} "
            f"old_version={domain.get('old_version')} new_version={domain.get('new_version')}"
        )
        print(f"jobs:       {list(payload['jobs'])}")
        for name, job in payload["jobs"].items():
            history = job.get("history") or []
            print(
                f"  - {name}: job_id={job.get('job_id')} "
                f"remote_job_status={job.get('remote_job_status') or job.get('status')} "
                f"review_outcome={job.get('review_outcome') or job.get('human_decision')} "
                f"mutation_applied={job.get('mutation_applied')} "
                f"domain_applied={job.get('domain_applied')} "
                f"verified={job.get('verified')} "
                f"attempt={job.get('attempt')} history={len(history)} "
                f"action={reviewed_job_action(job)}"
            )
            for index, prior in enumerate(history, start=1):
                print(
                    f"      history[{index}]: job_id={prior.get('job_id')} "
                    f"review_outcome={prior.get('review_outcome') or prior.get('human_decision')} "
                    f"mutation_applied={prior.get('mutation_applied')} "
                    f"operation_key={prior.get('operation_key')}"
                )
        if payload.get("last_error"):
            print(f"last_error: {payload['last_error']}")
        return 0
    if args.command == "verify-profile-structure":
        path = args.path
        if path is None:
            print("--path to the exported or filled profile DOCX is required", file=sys.stderr)
            return 2
        if not path.is_file():
            print(f"File not found: {path}", file=sys.stderr)
            return 2
        layout = inspect_docx_layout(path)
        report = validate_profile_document_text(layout.text, layout=layout.as_dict())
        print(f"path: {path}")
        print(f"semantic ok: {report.ok}")
        print(f"field_counts: {report.field_counts}")
        print(f"section_counts: {report.section_counts}")
        if report.field_values:
            print("field_values:")
            for key, value in report.field_values.items():
                print(f"  - {key}: {value}")
        print(
            "physical: "
            f"paragraphs={layout.paragraph_count} runs={layout.run_count} breaks={layout.break_count}; "
            f"level_expectations paragraphs={layout.level_expectations_paragraphs} "
            f"runs={layout.level_expectations_runs} breaks={layout.level_expectations_breaks}"
        )
        if report.violations:
            print("violations:")
            for item in report.violations:
                print(f"  - {item}")
        else:
            print("violations: (none)")
        state = load_and_prepare(store)
        if state is not None:
            record_structure_verification(state, path=str(path), report=report)
            if report.ok:
                from job_architecture.live.integrity import mark_structure_verified

                mark_structure_verified(state, path=str(path))
                print("Recorded profile_integrity=verified and structure verification.")
            store.save(state)
        if not report.ok:
            print("Structure is invalid. Not marking the live baseline verified.")
        print("Local structure check only. No SuperDocs call.")
        return 0 if report.ok else 1
    if args.command == "verify-framework-structure":
        path = args.path or (DEFAULT_EXPORTS / "framework.docx")
        if not path.is_file():
            print(f"File not found: {path}", file=sys.stderr)
            return 2
        check = verify_exported_framework(path)
        print(f"path: {path}")
        print(f"semantic ok: {check.ok}")
        print(f"found: {', '.join(check.found_markers) or '(none)'}")
        print(f"missing: {', '.join(check.missing_markers) or '(none)'}")
        print(f"looks_like_source_jd: {check.looks_like_source_jd}")
        print("excerpt:")
        print(check.excerpt[:500])
        print("File existence is not success. Local check only. No SuperDocs call.")
        if not check.ok:
            print("Framework export is NOT VERIFIED.")
        return 0 if check.ok else 1
    if args.command == "finalize-domain":
        state = load_and_prepare(store)
        if state is None:
            print(f"No runtime state at {store.path}", file=sys.stderr)
            return 2
        subset = load_demo_subset()
        _architecture, framework = build_demo_framework(subset)
        try:
            _framework, result = apply_verified_domain(framework, subset, state)
        except SuperDocsError as exc:
            print(exc, file=sys.stderr)
            store.save(state)
            return 1
        store.save(state)
        print("Local domain apply only. No SuperDocs call.")
        print(
            f"domain_applied={result['domain_applied']} idempotent={result['idempotent']} "
            f"level_id={result.get('level_id')} "
            f"old_version={result.get('old_version')} new_version={result.get('new_version')}"
        )
        job = state.jobs.get("surgical") or {}
        print(
            f"surgical: review_outcome={job.get('review_outcome')} "
            f"mutation_applied={job.get('mutation_applied')} "
            f"domain_applied={job.get('domain_applied')} "
            f"history={len(job.get('history') or [])}"
        )
        return 0
    path = args.path
    if path is None:
        print("--path to the exported DOCX is required", file=sys.stderr)
        return 2
    if not path.is_file():
        print(f"File not found: {path}", file=sys.stderr)
        return 2
    state = load_and_prepare(store)
    if state is None or not state.preservation:
        print("No preservation hashes in runtime state. Run surgical-update first.", file=sys.stderr)
        return 2
    markers = {
        "purpose": str(state.preservation.get("preserved_purpose") or ""),
        "responsibilities": str(state.preservation.get("preserved_responsibilities") or ""),
    }
    markers = {key: value for key, value in markers.items() if value}
    result = verify_exported_profile(
        path,
        expected_new_fragment=str(state.preservation.get("expected_after_fragment") or ""),
        preserved_markers=markers,
    )
    record_preservation_verification(state, path=str(path), check=result)
    store.save(state)
    print(f"found new fragment: {result.found_new_fragment}")
    print(f"preserved markers:  {', '.join(result.preserved_markers) or '(none)'}")
    print(f"missing markers:    {', '.join(result.missing_markers) or '(none)'}")
    print(f"preservation ok:    {result.ok}")
    print("This checks extracted Word text, not DOCX container bytes. No SuperDocs call.")
    return 0 if result.ok else 1


def _run_mutating(args, intent: LiveIntent, action) -> int:
    print(f"intent: {intent.action}")
    print(intent.summary)
    print(f"estimated mutating SuperDocs calls: {intent.estimated_count}")
    for item in intent.mutating_calls:
        print(f"  - {item}")
    if intent.estimated_count == 0:
        if "blind retry" in intent.summary:
            print("Not treating the completed remote job as an applied mutation.")
        elif "Refusing surgical-update" in intent.summary:
            print("Surgical-update is blocked until the live profile baseline is structurally valid.")
        else:
            print("Nothing new to send; resuming from saved non-secret ids.")
    elif not _confirmed(args):
        print("Aborted. Re-run with --confirm, or type YES at the prompt.")
        return 2
    try:
        return action()
    except SuperDocsError as exc:
        print(exc, file=sys.stderr)
        print("Runtime state was saved. Inspect with: python scripts/superdocs_live.py status")
        return 1


def _confirmed(args) -> bool:
    if args.confirm:
        return True
    if not sys.stdin.isatty():
        print("Pass --confirm to execute this mutating live call.")
        return False
    answer = input("Type YES to execute this SuperDocs mutating call: ")
    return answer.strip() == "YES"


def _do_upload(orchestrator: LiveOrchestrator) -> int:
    roster = orchestrator.setup()
    print(f"session {roster.session_id} roster count={len(roster.documents)}")
    for item in roster.documents:
        print(f"  - document_id={item.document_id} durable={item.durable_document_id} title={item.title}")
    if len({item.document_id for item in roster.documents}) != len(roster.documents):
        print("Roster document ids are not unique.", file=sys.stderr)
        return 1
    print("persisted document ids after roster reconcile:")
    for item in orchestrator.state().documents:
        print(
            f"  - {item.get('role_id')} document_id={item.get('document_id')} "
            f"durable={item.get('durable_document_id')}"
        )
    templates = orchestrator.state().templates
    for name, item in templates.items():
        print(f"template {name}: template_id={item.get('template_id')}")
    print("Multi-document check passed. Documents coexist in one session.")
    return 0


def _do_profile(orchestrator: LiveOrchestrator) -> int:
    result = orchestrator.start_profile()
    print(
        f"authoritative filled profile uploaded: profile_id={result.profile_id} "
        f"document_id={result.document_id} integrity={result.integrity_status} "
        f"structure_ok={result.structure_ok}"
    )
    print("No SuperDocs fill edit was sent. SuperDocs must not regenerate decided profile semantics.")
    if result.integrity_status == "needs_repair":
        print("Existing live profile still needs reviewed duplicate-section repair.")
        print("Next: python scripts/superdocs_live.py repair-profile --confirm")
    return 0


def _do_job(start, job_name: str) -> int:
    snapshot = start()
    print(format_pending(snapshot))
    if snapshot.status == "awaiting_approval":
        print(f"Stopped at human approval for {job_name}. No automatic decision.")
        print(
            "Next: python scripts/superdocs_live.py decide "
            f"--job {job_name} --change CHANGE_ID:approve --confirm"
        )
        return 0
    print(f"job status={snapshot.status}")
    return 0


def _do_search(orchestrator: LiveOrchestrator) -> int:
    try:
        outcome = orchestrator.poll_search()
    except JobTimeoutError as exc:
        print(exc)
        job = orchestrator.state().jobs.get("search") or {}
        print(
            f"search still {job.get('remote_job_status') or job.get('status')}; "
            "not marking Search verification complete. Re-run search to poll the same job id."
        )
        return 1
    except JobFailedError as exc:
        print(exc, file=sys.stderr)
        print("Search reached failed. Not posting another search. Not marking Search verification complete.")
        return 1
    accepted = outcome["accepted"]
    snapshot = outcome["snapshot"]
    print(
        f"search job_id={accepted.handle.job_id} "
        f"status={snapshot.status} posted={outcome['posted']} "
        f"query={accepted.query!r}"
    )
    print(format_pending(snapshot))
    job = orchestrator.state().jobs.get("search") or {}
    print(
        f"search verified={job.get('verified')} terminal={job.get('terminal')} "
        f"has_result={job.get('has_result')}"
    )
    if job.get("verified"):
        print("Search reached a valid terminal completed result.")
    else:
        print("Search verification is not complete until this job reaches a valid terminal result.")
    print("Search is demonstration-only. The structured dependency graph remains the surgical authority.")
    return 0 if job.get("verified") else 1


def _do_decide(orchestrator: LiveOrchestrator, job_name: str, decisions: list[ReviewDecision]) -> int:
    snapshot = orchestrator.submit_decisions(job_name, decisions)
    print(f"submitted {len(decisions)} explicit decision(s)")
    print(format_pending(snapshot))
    job = orchestrator.state().jobs.get(job_name) or {}
    print(
        f"review_outcome={job.get('review_outcome')} "
        f"mutation_applied={job.get('mutation_applied')} "
        f"domain_applied={job.get('domain_applied')} "
        f"remote_job_status={job.get('remote_job_status') or snapshot.status}"
    )
    for item in job.get("review_decisions") or []:
        verdict = "approve" if item.get("approved") else "reject"
        print(f"  - {item.get('change_id')}: {verdict}")
    if snapshot.awaiting_kind == "continue_prompt":
        print(f"continue_prompt received. Run: python scripts/superdocs_live.py continue --job {job_name} --confirm")
    return 0


def _do_export(orchestrator: LiveOrchestrator, kind: str, destination: Path) -> int:
    path = orchestrator.export(kind, destination)
    print(f"exported {kind} to {path}")
    print("Compare extracted text, not DOCX package metadata bytes.")
    if kind != "framework":
        return 0
    check = verify_exported_framework(path)
    print(f"semantic framework verification: {'PASS' if check.ok else 'FAIL'}")
    print(f"found: {', '.join(check.found_markers) or '(none)'}")
    print(f"missing: {', '.join(check.missing_markers) or '(none)'}")
    print(f"looks_like_source_jd: {check.looks_like_source_jd}")
    print("File existence is not success.")
    if not check.ok:
        print("Framework export is NOT VERIFIED. The HTTP response may still be a wrong document.")
        return 1
    return 0


def _latest_review_job(orchestrator: LiveOrchestrator) -> str | None:
    state = orchestrator.state()
    names = ("profile_repair", "surgical", "profile", "framework")
    for name in names:
        job = state.jobs.get(name) or {}
        if (job.get("remote_job_status") or job.get("status")) == "awaiting_approval":
            return name
    for name in names:
        job = state.jobs.get(name) or {}
        if job.get("job_id"):
            return name
    return None


def _parse_decisions(raw: list[str]) -> list[ReviewDecision]:
    decisions: list[ReviewDecision] = []
    for item in raw:
        if ":" not in item:
            raise SuperDocsError(f"Decision {item!r} must look like change_id:approve or change_id:reject")
        change_id, verdict = item.rsplit(":", 1)
        verdict = verdict.strip().lower()
        if verdict not in {"approve", "reject"}:
            raise SuperDocsError(f"Unknown verdict {verdict!r}; use approve or reject")
        decisions.append(ReviewDecision(change_id=change_id.strip(), approved=verdict == "approve"))
    return decisions


if __name__ == "__main__":
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise SystemExit("Live SuperDocs script must not run under pytest")
    raise SystemExit(main())
