"""Build the study corpus: real SuperDocs change batches + pre-registered labels.

Usage:
    python corpus_builder.py --mode pilot            # 1 doc, <=5 ops
    python corpus_builder.py --mode full             # all docs, <=15 ops
    python corpus_builder.py --mode pilot --offline tests/fixtures/job_doc01.json

Design notes that matter:

*Checkpointing.* The raw job payload is written to
`study_data/checkpoints/<doc_id>.job.json` the moment it arrives, before any
parsing. A crash after that point costs nothing to recover -- a rerun reuses
the checkpoint instead of re-spending the operation. Parsing bugs are cheap;
re-billing is not.

*Warm-up.* The first request in a fresh session can be slow or fail while the
backend warms up, so we send one throwaway instruction first and tolerate its
failure. Its cost, if any, still counts against the cap (PROGRESS.md A6).

*Labels.* Never invented here. Only intents from `corpus/edit_specs.py` that
are matched to a returned change get labelled; anything else is reported as
unmatched for explicit human labelling.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus.edit_specs import (
    ALL_DOCUMENTS,
    PILOT_DOCUMENTS,
    STUDY_DOCUMENTS,
    DocumentSpec,
    EditIntent,
)
from ground_truth import (
    Change,
    LabelledChange,
    UnconfirmedLabel,
    build_batch,
    verify_ground_truth,
)
from superdocs_client import (
    BudgetExceeded,
    OpsLedger,
    SuperDocsClient,
    SuperDocsError,
    load_dotenv,
)

REPO = Path(__file__).resolve().parent
STUDY_DATA = REPO / "study_data"
CHECKPOINTS = STUDY_DATA / "checkpoints"
BATCHES_PATH = STUDY_DATA / "batches.json"
LEDGER_PATH = STUDY_DATA / "ops_ledger.jsonl"

PILOT_OPS_CAP = 5
FULL_OPS_CAP = 15


@dataclass
class MatchResult:
    labelled: list[LabelledChange]
    unmatched: list[dict[str, Any]]
    missing: list[str]


def strip_tags(html: str | None) -> str:
    """Visible text only, whitespace-normalised. For no-op detection."""
    return " ".join(re.sub(r"<[^>]+>", " ", html or "").split())


def is_noop(change: dict[str, Any]) -> bool:
    """True when a proposed change would not alter the document text.

    The live pilot returned two of these: SuperDocs proposed an edit whose
    new_html was textually identical to old_html. They must never reach a
    reviewer -- asking someone to approve or reject a change that changes
    nothing is a meaningless trial that still contributes a decision time and
    a vote to the agreement statistics, quietly polluting both.

    A delete is never a no-op: removing content is a real change.
    """
    if (change.get("operation") or "").lower() in ("delete", "remove"):
        return False
    return strip_tags(change.get("old_html")) == strip_tags(change.get("new_html"))


def load_confirmations(path: Path) -> dict[str, dict[str, Any]]:
    """Human-confirmed labels, keyed by change_id (GT-7)."""
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("confirmations", payload)
    return {r["change_id"]: r for r in records}


def apply_confirmations(
    labelled: list[LabelledChange], confirmations: dict[str, dict[str, Any]]
) -> list[LabelledChange]:
    """Promote provisional intent labels to confirmed ones.

    A confirmation may overturn the intent; when it does, the original intent
    verdict is preserved in `intent_said_approve` so the override stays on the
    record rather than vanishing (GT-7).
    """
    out: list[LabelledChange] = []
    for item in labelled:
        record = confirmations.get(item.change.change_id)
        if record is None:
            out.append(item)  # stays provisional; build_batch will refuse it
            continue
        out.append(
            LabelledChange(
                change=item.change,
                should_approve=bool(record["should_approve"]),
                reason=record.get("reason", item.reason),
                error_kind=record.get("error_kind"),
                confirmed_by=record.get("confirmed_by", "designer"),
                confirmed_at=record.get("confirmed_at", ""),
                intent_said_approve=item.should_approve,
            )
        )
    return out


def _text_of(change: dict[str, Any]) -> str:
    """Everything we can search for a marker, old side first."""
    return " ".join(
        str(change.get(field) or "")
        for field in ("old_html", "new_html", "ai_explanation")
    )


def match_changes_to_intents(
    changes: list[dict[str, Any]], intents: tuple[EditIntent, ...]
) -> MatchResult:
    """Attach pre-registered labels to the changes that actually arrived.

    Matching is by content marker, old side preferred: a deletion has its
    marker only in old_html, a correction has it in old_html and its
    replacement in new_html.

    Anything unmatched is surfaced, never guessed at (see module docstring).
    """
    labelled: list[LabelledChange] = []
    unmatched: list[dict[str, Any]] = []
    claimed: set[str] = set()

    for change in changes:
        old_html = str(change.get("old_html") or "")
        haystack = _text_of(change)

        hit: EditIntent | None = None
        for intent in intents:
            if intent.key in claimed:
                continue
            if intent.old_marker in old_html:
                hit = intent
                break
        if hit is None:
            for intent in intents:
                if intent.key in claimed:
                    continue
                if intent.old_marker in haystack:
                    hit = intent
                    break

        if hit is None:
            unmatched.append(change)
            continue

        claimed.add(hit.key)
        labelled.append(
            LabelledChange(
                change=Change.from_pending(change),
                should_approve=hit.should_approve,
                reason=hit.reason,
                error_kind=hit.error_kind,
            )
        )

    missing = [i.key for i in intents if i.key not in claimed]
    return MatchResult(labelled=labelled, unmatched=unmatched, missing=missing)


def checkpoint_path(doc_id: str) -> Path:
    return CHECKPOINTS / f"{doc_id}.job.json"


def load_checkpoint(doc_id: str) -> dict[str, Any] | None:
    path = checkpoint_path(doc_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[warn] checkpoint for {doc_id} is corrupt; ignoring it")
        return None


def load_all_checkpoints(doc_id: str) -> list[dict[str, Any]]:
    """Every job recorded for a document, oldest slot first.

    A document can take more than one call: the live pilot showed SuperDocs
    silently skipping structural edits (delete, merge), so the remainder are
    requested in a follow-up call and land in `<doc_id>_b.job.json` etc. All
    of them contribute changes to the same batch.
    """
    jobs: list[dict[str, Any]] = []
    for path in sorted(CHECKPOINTS.glob(f"{doc_id}.job.json")) + sorted(
        CHECKPOINTS.glob(f"{doc_id}_*.job.json")
    ):
        try:
            jobs.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            print(f"[warn] checkpoint {path.name} is corrupt; ignoring it")
    return jobs


def merge_changes(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pending changes across several jobs, deduped by change_id."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in jobs:
        for change in SuperDocsClient.extract_pending_changes(job):
            cid = change.get("change_id")
            if cid and cid in seen:
                continue
            if cid:
                seen.add(cid)
            merged.append(change)
    return merged


def save_checkpoint(doc_id: str, job: dict[str, Any], *, slot: str = "") -> None:
    """Persist the raw job before parsing it. Never re-spend an operation."""
    CHECKPOINTS.mkdir(parents=True, exist_ok=True)
    path = checkpoint_path(f"{doc_id}_{slot}" if slot else doc_id)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash mid-write cannot leave a partial file
    print(f"[checkpoint] saved raw job for {doc_id} -> {path.relative_to(REPO)}")


def warm_up(client: SuperDocsClient) -> None:
    """One throwaway call to absorb cold-start slowness or failure.

    Deliberately does not raise: a failed warm-up is the expected case the
    brief warns about, not an error condition. It has done its job either way.
    """
    session_id = f"warmup_{int(time.time())}"
    print("[warmup] sending one throwaway instruction (failure here is expected/ok)")
    try:
        job_id = client.chat_async(
            message="Reply with the single word: ready.",
            session_id=session_id,
            document_html="<p>Warm-up. Ignore this document.</p>",
            approval_mode="approve_all",
            label="warmup",
        )
        client.poll_job(job_id, timeout_s=180.0, label="warmup")
        print("[warmup] backend responded; proceeding")
    except BudgetExceeded:
        raise
    except SuperDocsError as exc:
        print(f"[warmup] failed as anticipated ({exc}); proceeding to the real call")


def request_edits(
    client: SuperDocsClient,
    spec: DocumentSpec,
    intents: tuple[EditIntent, ...],
    *,
    slot: str = "",
    session_suffix: str = "",
) -> dict[str, Any]:
    """One billable call requesting the given intents. Checkpoints on arrival."""
    session_id = f"corpus_{spec.doc_id}{session_suffix}"
    label = f"corpus:{spec.doc_id}{('_' + slot) if slot else ''}"
    print(f"[{spec.doc_id}] requesting {len(intents)} edit(s) in one call ({label})")
    job_id = client.chat_async(
        message=spec.build_message(intents),
        session_id=session_id,
        document_html=spec.html,
        approval_mode="ask_every_time",
        label=label,
    )
    print(f"[{spec.doc_id}] job {job_id}; polling")
    job = client.poll_job(job_id, timeout_s=600.0, label=label)
    save_checkpoint(spec.doc_id, job, slot=slot)
    return job


def fill_missing_intents(client: SuperDocsClient, spec: DocumentSpec) -> None:
    """Re-request the edits SuperDocs skipped, in one follow-up call.

    A fresh session is used rather than the original: that job is parked at
    `awaiting_approval`, and sending a second message into a session with
    unapproved changes has undefined behaviour. The skipped edits touch chunks
    the successful ones never modified, so requesting them against the pristine
    document is coherent.
    """
    jobs = load_all_checkpoints(spec.doc_id)
    if not jobs:
        raise SuperDocsError(f"[{spec.doc_id}] nothing to fill in; no checkpoints yet")

    result = match_changes_to_intents(merge_changes(jobs), spec.intents)
    if not result.missing:
        print(f"[{spec.doc_id}] nothing missing; no follow-up call needed")
        return

    missing = spec.intents_by_key(result.missing)
    # Next free slot letter, so a second retry does not overwrite the evidence
    # from the first -- diagnosing why a document keeps failing needs both.
    # p.stem on "doc04_b.job.json" is "doc04_b.job", so strip every suffix
    # before taking the slot letter -- getting this wrong reused a session that
    # still had a job awaiting approval and earned an HTTP 409 session_busy.
    used = {
        p.name.split(".")[0].split("_")[-1]
        for p in CHECKPOINTS.glob(f"{spec.doc_id}_*.job.json")
    }
    slot = next(c for c in "bcdefghij" if c not in used)
    print(f"[{spec.doc_id}] following up on {len(missing)} skipped intent(s) "
          f"(slot {slot}): {', '.join(result.missing)}")
    request_edits(client, spec, missing, slot=slot, session_suffix=f"_{slot}")


def build_document(
    client: SuperDocsClient | None,
    spec: DocumentSpec,
    *,
    offline: Path | None = None,
    confirmations: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Produce one batch for one document, reusing checkpoints when present."""
    confirmations = confirmations or {}
    jobs: list[dict[str, Any]] = []

    if offline is not None:
        print(f"[{spec.doc_id}] offline mode: replaying {offline}")
        jobs = [json.loads(offline.read_text(encoding="utf-8"))]
    else:
        jobs = load_all_checkpoints(spec.doc_id)
        if jobs:
            print(f"[{spec.doc_id}] reusing {len(jobs)} checkpoint(s); no operation spent")

    if not jobs:
        if client is None:
            raise SuperDocsError("no client available and no checkpoint to reuse")
        jobs = [request_edits(client, spec, spec.intents)]

    job = jobs[-1]
    all_changes = merge_changes(jobs)
    changes = [c for c in all_changes if not is_noop(c)]
    dropped = len(all_changes) - len(changes)
    print(f"[{spec.doc_id}] SuperDocs proposed {len(all_changes)} change(s) across "
          f"{len(jobs)} call(s)")
    if dropped:
        print(f"[{spec.doc_id}] dropped {dropped} no-op change(s) "
              f"(new text identical to old); they would be meaningless trials")
    if not changes:
        raise SuperDocsError(
            f"[{spec.doc_id}] job returned no pending changes "
            f"(status={job.get('status')!r}). Nothing to label."
        )

    # The confirmations file covers every document, so most entries belong to
    # other documents. Narrow to this one; ids matching nothing anywhere are
    # caught once, globally, by check_orphan_confirmations().
    known_ids = {c.get("change_id") for c in all_changes}
    confirmations = {
        cid: record for cid, record in confirmations.items() if cid in known_ids
    }

    result = match_changes_to_intents(changes, spec.intents)
    print(
        f"[{spec.doc_id}] matched {len(result.labelled)}/{len(spec.intents)} intents; "
        f"{len(result.unmatched)} unmatched change(s)"
    )
    for key in result.missing:
        print(f"[{spec.doc_id}]   MISSING intent (not performed): {key}")
    # An unmatched change can still be a real, labellable change -- the pilot's
    # lossy merge arrived as two changes and only the first matched an intent.
    # It enters the batch only if a human confirmed a label for it.
    adopted: list[LabelledChange] = []
    for change in result.unmatched:
        cid = change.get("change_id", "")
        record = confirmations.get(cid)
        if record is None:
            print(
                f"[{spec.doc_id}]   UNMATCHED change {cid} "
                f"-> no confirmed label, excluded from the answer key"
            )
            continue
        adopted.append(
            LabelledChange(
                change=Change.from_pending(change),
                should_approve=bool(record["should_approve"]),
                reason=record.get("reason", ""),
                error_kind=record.get("error_kind"),
                confirmed_by=record.get("confirmed_by", "designer"),
                confirmed_at=record.get("confirmed_at", ""),
            )
        )
        print(f"[{spec.doc_id}]   UNMATCHED change {cid} -> adopted via confirmed label")

    labelled = apply_confirmations(result.labelled, confirmations) + adopted

    batch = build_batch(
        batch_id=f"batch_{spec.doc_id}",
        document_id=spec.doc_id,
        document_title=spec.title,
        document_html=spec.html,
        labelled=labelled,
        seed=spec.seed,
    )
    batch["exclude_from_study"] = spec.exclude_from_study
    batch["build_report"] = {
        "intents_requested": len(spec.intents),
        "intents_matched": len(result.labelled),
        "missing_intents": result.missing,
        "unmatched_changes": [c.get("change_id") for c in result.unmatched],
        "adopted_unmatched": [lc.change.change_id for lc in adopted],
        "noops_dropped": dropped,
        "labels_overriding_intent": [
            lc.change.change_id for lc in labelled if lc.overrides_intent
        ],
        "job_status": job.get("status"),
        "job_ids": [j.get("job_id") for j in jobs],
        "calls_made": len(jobs),
    }
    verify_ground_truth(batch)
    return batch


def check_orphan_confirmations(
    confirmations: dict[str, dict[str, Any]], specs: tuple[DocumentSpec, ...]
) -> list[str]:
    """Confirmations whose change_id exists in no checkpoint of any document.

    A mistyped id would otherwise be silently ignored, shrinking the answer key
    without saying so -- which happened for real while writing doc01's
    confirmations (PROGRESS.md A13). Checked across all documents at once,
    because the confirmations file is global while each build is per-document.
    """
    known: set[str] = set()
    for spec in specs:
        for change in merge_changes(load_all_checkpoints(spec.doc_id)):
            cid = change.get("change_id")
            if cid:
                known.add(cid)
    return sorted(cid for cid in confirmations if cid not in known)


def propose_labels(spec: DocumentSpec, path: Path) -> int:
    """Write a review file: every real change, its diff, and a proposed label.

    This is the human step GT-7 requires. Nothing here is authoritative until a
    person has read the diffs and signed the file off; the proposals are
    starting points derived from the intent, and the pilot proved those can be
    wrong.
    """
    jobs = load_all_checkpoints(spec.doc_id)
    if not jobs:
        raise SuperDocsError(f"[{spec.doc_id}] no checkpoints; run the builder first")

    all_changes = merge_changes(jobs)
    changes = [c for c in all_changes if not is_noop(c)]
    result = match_changes_to_intents(changes, spec.intents)
    by_source = {lc.change.change_id: lc for lc in result.labelled}

    entries = []
    for change in changes:
        cid = change["change_id"]
        provisional = by_source.get(cid)
        entries.append(
            {
                "change_id": cid,
                "operation": change.get("operation"),
                "old_text": strip_tags(change.get("old_html")),
                "new_text": strip_tags(change.get("new_html")) or "<<DELETED>>",
                "matched_intent": next(
                    (
                        i.key
                        for i in spec.intents
                        if provisional and i.reason == provisional.reason
                    ),
                    None,
                ),
                "proposed_should_approve": (
                    provisional.should_approve if provisional else None
                ),
                "proposed_error_kind": provisional.error_kind if provisional else None,
                "proposed_reason": provisional.reason if provisional else "",
                # to be filled in by the reviewer
                "should_approve": None,
                "error_kind": None,
                "reason": "",
                "confirmed_by": "",
                "confirmed_at": "",
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "document_id": spec.doc_id,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "instructions": (
                    "Read old_text vs new_text for each entry and fill in "
                    "should_approve, error_kind, reason, confirmed_by and "
                    "confirmed_at. The proposed_* fields are intent-derived "
                    "starting points and may be wrong -- that is why this file "
                    "exists. Entries left unconfirmed are excluded from the study."
                ),
                "noops_excluded": [
                    c["change_id"] for c in all_changes if is_noop(c)
                ],
                "confirmations": entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[{spec.doc_id}] wrote {len(entries)} change(s) for review -> {path}")
    print(f"[{spec.doc_id}] excluded {len(all_changes) - len(changes)} no-op(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=("pilot", "study", "full"), default="pilot",
        help="pilot=doc01 only; study=the four 2x2 documents; full=everything.",
    )
    parser.add_argument(
        "--offline",
        type=Path,
        default=None,
        help="Replay a saved job payload instead of calling the API (no key needed).",
    )
    parser.add_argument("--skip-warmup", action="store_true")
    parser.add_argument(
        "--fill-missing",
        action="store_true",
        help="Make one follow-up call per document for intents SuperDocs skipped.",
    )
    parser.add_argument(
        "--propose-labels",
        action="store_true",
        help="Write study_data/label_review_<doc>.json for human confirmation (GT-7). "
        "Spends no operations.",
    )
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated doc_ids to act on, e.g. --only doc04. Lets a single "
        "failed document be retried without re-spending on the rest.",
    )
    parser.add_argument(
        "--confirmations",
        type=Path,
        default=None,
        help="Confirmed labels to build from. Defaults to study_data/confirmations.json.",
    )
    parser.add_argument(
        "--max-ops",
        type=int,
        default=None,
        help="Override the operation ceiling. Defaults to 5 (pilot) / 15 (full).",
    )
    args = parser.parse_args(argv)

    load_dotenv(REPO / ".env")
    specs = {
        "pilot": PILOT_DOCUMENTS,
        "study": STUDY_DOCUMENTS,
        "full": ALL_DOCUMENTS,
    }[args.mode]
    if args.only:
        wanted = {d.strip() for d in args.only.split(",") if d.strip()}
        specs = tuple(s for s in ALL_DOCUMENTS if s.doc_id in wanted)
        unknown = wanted - {s.doc_id for s in specs}
        if unknown:
            print(f"ERROR: unknown doc_id(s) in --only: {sorted(unknown)}")
            return 2

    cap = args.max_ops or (PILOT_OPS_CAP if args.mode == "pilot" else FULL_OPS_CAP)

    if args.propose_labels:
        for spec in specs:
            propose_labels(spec, STUDY_DATA / f"label_review_{spec.doc_id}.json")
        return 0

    conf_path = args.confirmations or (STUDY_DATA / "confirmations.json")
    confirmations = load_confirmations(conf_path)
    if confirmations:
        print(f"[labels] loaded {len(confirmations)} confirmed label(s) from {conf_path.name}")
        # Skipped for --offline replay: the changes come from the replayed file,
        # not from checkpoints, so checkpoints are not the right universe.
        orphans = (
            [] if args.offline else check_orphan_confirmations(confirmations, ALL_DOCUMENTS)
        )
        if orphans:
            print(
                f"ERROR: {len(orphans)} confirmation(s) reference change_ids that "
                f"exist in no checkpoint of any document: {orphans}\n"
                "Fix the ids rather than letting those labels go missing."
            )
            return 2

    print(f"=== corpus_builder: mode={args.mode} docs={len(specs)} cap={cap} ops ===")

    client: SuperDocsClient | None = None
    if args.offline is None:
        ledger = OpsLedger(path=LEDGER_PATH)
        ledger.load()  # prior spend counts; a restart does not reset the budget
        if ledger.total_ops:
            print(f"[ops] prior spend on record: {ledger.total_ops} operation(s)")
        try:
            client = SuperDocsClient(max_operations=cap, ledger=ledger)
        except SuperDocsError as exc:
            print(f"ERROR: {exc}")
            return 2
        if not client.verify_key():
            print("ERROR: SUPERDOCS_API_KEY was rejected (401/403). Check the key.")
            return 2
        print("[auth] key accepted")

        # Only warm up if a billable call is actually coming. A rerun that
        # reuses checkpoints needs no warm-up, and running one anyway spends a
        # real operation for nothing -- which is exactly what happened on
        # 2026-08-14 before this guard existed.
        work_pending = args.fill_missing or any(
            not load_all_checkpoints(spec.doc_id) for spec in specs
        )
        if args.skip_warmup:
            pass
        elif not work_pending:
            print("[warmup] skipped: every document has a checkpoint, nothing to call")
        else:
            warm_up(client)

    batches: list[dict[str, Any]] = []
    needs_labels: list[str] = []
    failed: list[str] = []
    for spec in specs:
        try:
            if args.fill_missing and client is not None:
                fill_missing_intents(client, spec)
            batches.append(
                build_document(
                    client, spec, offline=args.offline, confirmations=confirmations
                )
            )
        except BudgetExceeded as exc:
            print(f"\nSTOPPED ON BUDGET: {exc}")
            break
        except UnconfirmedLabel as exc:
            # Expected on a first capture: the changes are checkpointed but
            # nobody has confirmed their labels yet (GT-7). Keep going so the
            # remaining documents are captured in the same run -- the
            # operations are already spent either way.
            print(f"\n[{spec.doc_id}] captured, labels not yet confirmed:\n  {exc}")
            needs_labels.append(spec.doc_id)
            continue
        except SuperDocsError as exc:
            # Per-document failure, not a run failure. doc04 came back with a
            # single no-op change on 2026-08-14 and aborted the whole run,
            # leaving doc05 unbuilt for no reason -- the operations for the
            # remaining documents are independent of this one.
            print(f"\nERROR building {spec.doc_id}: {exc}")
            failed.append(spec.doc_id)
            continue

    if failed:
        print(f"\n=== {len(failed)} document(s) FAILED: {', '.join(failed)} ===")
        print("Retry one with: --only <doc_id> --fill-missing")

    if needs_labels:
        print(
            f"\n=== {len(needs_labels)} document(s) awaiting label confirmation: "
            f"{', '.join(needs_labels)} ==="
        )
        print("Next: python corpus_builder.py --mode study --propose-labels  (0 operations)")

    if not batches:
        spent_now = client.ops_used if client else 0
        print(f"\nNo batches written yet. [ops] TOTAL SPENT THIS RUN: {spent_now}/{cap}")
        return 1

    STUDY_DATA.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": args.mode,
        "ops_cap": cap,
        "ops_spent": client.ops_used if client else 0,
        "batches": batches,
    }
    BATCHES_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n=== wrote {BATCHES_PATH.relative_to(REPO)} ===")
    for batch in batches:
        report = batch["build_report"]
        n_bad = sum(1 for r in batch["ground_truth"] if not r["should_approve"])
        print(
            f"  {batch['batch_id']}: {len(batch['changes'])} changes "
            f"({n_bad} seeded-bad), matched {report['intents_matched']}"
            f"/{report['intents_requested']} intents"
        )
    spent = client.ops_used if client else 0
    print(f"[ops] TOTAL SPENT THIS RUN: {spent}/{cap}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
