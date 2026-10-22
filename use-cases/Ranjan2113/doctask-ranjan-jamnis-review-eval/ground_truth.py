"""Ground-truth labelling, reviewer-safe serialization, and scoring.

Every design choice here is downstream of GROUND_TRUTH_SAFETY.md. Read that
first; the invariant IDs (GT-1..GT-6) are cited inline and are proven by
tests/test_ground_truth_safety.py.

The single rule that shapes this module: ground truth and reviewer-facing data
never live in the same object. They are joined by `change_id` at analysis time
and nowhere else.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

# GT-1: an explicit whitelist, never a blacklist. Anything not named here is
# invisible to reviewers, including fields added to the schema in future.
REVIEWER_VISIBLE_CHANGE_FIELDS: tuple[str, ...] = (
    "id",
    "operation",
    "chunk_id",
    "old_html",
    "new_html",
    "ai_explanation",
)

REVIEWER_VISIBLE_BATCH_FIELDS: tuple[str, ...] = (
    "batch_id",
    "document_id",
    "document_title",
    "document_html",
    "changes",
)

# The fields that constitute the pre-registered answer key. Confirmation
# provenance is included so GT-4's digest covers *who* stood behind a verdict,
# not just the verdict (GT-7).
GROUND_TRUTH_FIELDS: tuple[str, ...] = (
    "change_id",
    "should_approve",
    "reason",
    "error_kind",
    "confirmed_by",
    "confirmed_at",
)


class GroundTruthTampered(RuntimeError):
    """The ground-truth block no longer matches its pre-registered digest (GT-4)."""


class UnconfirmedLabel(RuntimeError):
    """A label was never checked against the change it labels (GT-7).

    Raised by build_batch rather than falling back to the intent-derived
    guess. The pilot on 2026-08-14 produced an intent-derived label that was
    simply wrong; defaulting to it would have inverted the scoring for every
    reviewer who judged that change correctly.
    """


@dataclass(frozen=True)
class Change:
    """One AI-proposed change, exactly as SuperDocs described it."""

    change_id: str
    operation: str
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str | None

    @classmethod
    def from_pending(cls, payload: dict[str, Any]) -> "Change":
        return cls(
            change_id=payload["change_id"],
            operation=payload.get("operation", "replace"),
            chunk_id=payload.get("chunk_id"),
            old_html=payload.get("old_html"),
            new_html=payload.get("new_html"),
            ai_explanation=payload.get("ai_explanation"),
        )


@dataclass(frozen=True)
class LabelledChange:
    """A change plus the designer's pre-registered verdict on it.

    `error_kind` is descriptive only (wrong_number, dropped_clause,
    meaning_flip, lossy_merge) and exists so the write-up can say *which*
    error types reviewers miss, not just how many.

    A label is only usable once `confirmed_by`/`confirmed_at` are set, meaning
    a human compared the verdict against the change's real old/new HTML
    (GT-7). `intent_said_approve` preserves what the intent originally
    proposed, so a confirmation that *overturned* the intent stays visible
    instead of quietly replacing it.
    """

    change: Change
    should_approve: bool
    reason: str
    error_kind: str | None = None
    confirmed_by: str | None = None
    confirmed_at: str | None = None
    intent_said_approve: bool | None = None

    @property
    def is_confirmed(self) -> bool:
        return bool(self.confirmed_by and self.confirmed_at)

    @property
    def overrides_intent(self) -> bool:
        return (
            self.intent_said_approve is not None
            and self.intent_said_approve != self.should_approve
        )


def _opaque_id(batch_id: str, source_change_id: str, seed: int) -> str:
    """Reviewer-facing id derived from identity only (GT-3).

    Deliberately does not take the label, the index, or the position as input.
    Flipping every label in a batch must leave these bytes unchanged, which is
    what test_gt3_ids_do_not_change_when_labels_flip asserts.
    """
    material = f"{batch_id}|{source_change_id}|{seed}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:12]


def ground_truth_digest(records: Iterable[dict[str, Any]]) -> str:
    """SHA-256 over the canonical answer key (GT-4).

    Normalizes to the four label fields and sorts keys, so cosmetic
    re-serialization does not trip the check but any value change does.
    """
    canonical = [
        {field: record.get(field) for field in GROUND_TRUTH_FIELDS}
        for record in records
    ]
    canonical.sort(key=lambda r: str(r["change_id"]))
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def build_batch(
    *,
    batch_id: str,
    document_id: str,
    document_html: str,
    labelled: list[LabelledChange],
    seed: int,
    document_title: str = "",
    require_confirmation: bool = True,
) -> dict[str, Any]:
    """Assemble one reviewable batch with its answer key kept separate.

    Returns a dict with two sibling blocks that must never be merged:
      - `changes`      -> reviewer-facing, shuffled, opaque ids
      - `ground_truth` -> the answer key, keyed by the SuperDocs change_id

    The shuffle (GT-2) is seeded from `seed` alone, so a session is exactly
    reproducible, and it operates on identity, never on the label.
    """
    # GT-7: refuse to pre-register anything a human has not checked against
    # the actual change. Never fall back to the intent-derived guess.
    if require_confirmation:
        unconfirmed = [
            item.change.change_id for item in labelled if not item.is_confirmed
        ]
        if unconfirmed:
            raise UnconfirmedLabel(
                f"batch {batch_id!r}: {len(unconfirmed)} label(s) never confirmed "
                f"against the change they label: {unconfirmed}. Run "
                f"`corpus_builder.py --propose-labels`, review the diffs, and "
                f"confirm before pre-registering."
            )

    # Shuffle on source ids only. The label is not in scope here -- that is
    # what keeps position uncorrelated with the answer (GT-2, GT-3).
    ordered = list(labelled)
    random.Random(seed).shuffle(ordered)

    changes: list[dict[str, Any]] = []
    for item in ordered:
        changes.append(
            {
                "id": _opaque_id(batch_id, item.change.change_id, seed),
                "source_change_id": item.change.change_id,
                "operation": item.change.operation,
                "chunk_id": item.change.chunk_id,
                "old_html": item.change.old_html,
                "new_html": item.change.new_html,
                "ai_explanation": item.change.ai_explanation,
            }
        )

    # Answer key sorted by source id -- deliberately NOT in presentation order,
    # so reading batches.json top-to-bottom does not reconstruct the sequence
    # a reviewer saw.
    ground_truth = sorted(
        (
            {
                "change_id": item.change.change_id,
                "should_approve": item.should_approve,
                "reason": item.reason,
                "error_kind": item.error_kind,
                "confirmed_by": item.confirmed_by,
                "confirmed_at": item.confirmed_at,
                "overrode_intent": item.overrides_intent,
            }
            for item in labelled
        ),
        key=lambda r: r["change_id"],
    )

    return {
        "batch_id": batch_id,
        "document_id": document_id,
        "document_title": document_title,
        "document_html": document_html,
        "seed": seed,
        "changes": changes,
        "ground_truth": ground_truth,
        "pre_registered_at": datetime.now(timezone.utc).isoformat(),
        "ground_truth_sha256": ground_truth_digest(ground_truth),
    }


def verify_ground_truth(batch: dict[str, Any]) -> None:
    """Raise if the answer key drifted from its pre-registration (GT-4).

    Called by analysis before it reports anything. Refusing to report is the
    correct behaviour: a silently-edited label turns the whole error-rate
    measurement into a post-hoc rationalisation.
    """
    recorded = batch.get("ground_truth_sha256")
    if not recorded:
        raise GroundTruthTampered(
            f"batch {batch.get('batch_id')!r} has no pre-registered digest"
        )
    actual = ground_truth_digest(batch.get("ground_truth", []))
    if actual != recorded:
        raise GroundTruthTampered(
            f"batch {batch.get('batch_id')!r}: ground truth was modified after "
            f"pre-registration at {batch.get('pre_registered_at')!r}. "
            f"expected sha256 {recorded}, got {actual}."
        )


def build_reviewer_view(batch: dict[str, Any]) -> dict[str, Any]:
    """The ONLY sanctioned path from a batch to reviewer-facing data (GT-1).

    Nothing else in the codebase may hand a batch to the UI. Field selection is
    a whitelist so it fails closed: an unrecognized field is dropped, not
    published. Carries no counts or ratios (GT-5).
    """
    changes = [
        {
            field: change.get(field)
            for field in REVIEWER_VISIBLE_CHANGE_FIELDS
            if field in change
        }
        for change in batch.get("changes", [])
    ]

    view = {
        "batch_id": batch.get("batch_id"),
        "document_id": batch.get("document_id"),
        "document_title": batch.get("document_title", ""),
        "document_html": batch.get("document_html"),
        "changes": changes,
    }
    return {k: v for k, v in view.items() if k in REVIEWER_VISIBLE_BATCH_FIELDS}


def make_decision_event(
    *,
    reviewer_id: str,
    batch_id: str,
    condition: str,
    reviewer_change_id: str,
    decision: str,
    shown_at: str,
    decided_at: str,
    engaged_at: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """One append-only decision record (GT-6).

    Stores what the reviewer did and when, and nothing about whether they were
    right. Correctness is computed at analysis time by joining to the answer
    key; denormalizing it here would put the key in the published raw timings.

    `decision_ms` runs from **engagement**, not render. In the batch conditions
    every change renders at once, so render-to-click for a later change
    includes all the time spent on earlier ones -- the artefact that made pilot
    run 1's timings meaningless (PROGRESS.md A18). `render_to_decision_ms` is
    kept alongside because it answers a different, legitimate question: how
    long the whole batch took.

    `engaged_at` defaults to `shown_at` so events from a client that does not
    report engagement still produce an interval rather than a null.
    """
    if decision not in ("approve", "reject", "skip"):
        raise ValueError(f"unknown decision {decision!r}")

    engaged = engaged_at or shown_at
    return {
        "reviewer_id": reviewer_id,
        "batch_id": batch_id,
        "condition": condition,
        "reviewer_change_id": reviewer_change_id,
        "decision": decision,
        "shown_at": shown_at,
        "engaged_at": engaged,
        "decided_at": decided_at,
        "decision_ms": _elapsed_ms(engaged, decided_at),
        "render_to_decision_ms": _elapsed_ms(shown_at, decided_at),
        "was_engaged": bool(engaged_at),
        "note": note,
    }


def _elapsed_ms(shown_at: str, decided_at: str) -> int | None:
    try:
        start = datetime.fromisoformat(shown_at)
        end = datetime.fromisoformat(decided_at)
    except ValueError:
        return None
    return int((end - start).total_seconds() * 1000)


def score_decisions(
    events: list[dict[str, Any]], batch: dict[str, Any]
) -> list[dict[str, Any]]:
    """Join decisions to the answer key by change_id (GT-6).

    The reviewer-facing opaque id is resolved back to the SuperDocs change_id
    here, in analysis, which is the only place both halves are in scope.
    """
    reviewer_to_source = {
        change["id"]: change["source_change_id"] for change in batch.get("changes", [])
    }
    key = {record["change_id"]: record for record in batch.get("ground_truth", [])}

    scored: list[dict[str, Any]] = []
    for event in events:
        if event.get("batch_id") != batch.get("batch_id"):
            continue
        source_id = reviewer_to_source.get(event.get("reviewer_change_id", ""))
        record = key.get(source_id) if source_id else None
        if record is None:
            continue
        decision = event["decision"]
        if decision == "skip":
            correct = None
        else:
            correct = (decision == "approve") == bool(record["should_approve"])
        scored.append(
            {
                **event,
                "source_change_id": source_id,
                "correct": correct,
                "expected_error_kind": record.get("error_kind"),
            }
        )
    return scored
