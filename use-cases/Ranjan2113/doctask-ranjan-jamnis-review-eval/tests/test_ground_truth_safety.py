"""Proofs for the invariants in GROUND_TRUTH_SAFETY.md.

These run with no API key and no network. Every test names the invariant it
defends so the mapping to the doc stays auditable.
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ground_truth import (  # noqa: E402
    REVIEWER_VISIBLE_CHANGE_FIELDS,
    Change,
    GroundTruthTampered,
    LabelledChange,
    UnconfirmedLabel,
    build_batch,
    build_reviewer_view,
    ground_truth_digest,
    make_decision_event,
    score_decisions,
    verify_ground_truth,
)

FORBIDDEN_SUBSTRINGS = (
    "should_approve",
    "should_reject",
    "ground_truth",
    "gt_reason",
    "error_kind",
    "seeded",
    "secret_future_field",
)


CONFIRMED = {"confirmed_by": "designer", "confirmed_at": "2026-08-14T10:00:00+00:00"}


def _labelled(n_good: int = 4, n_bad: int = 3) -> list[LabelledChange]:
    """A batch fixture with an uneven, non-obvious good/bad split.

    Labels carry confirmation stamps because GT-7 makes unconfirmed labels
    unbuildable; the unconfirmed case has its own tests below.
    """
    out: list[LabelledChange] = []
    for i in range(n_good):
        out.append(
            LabelledChange(
                change=Change(
                    change_id=f"sd_change_{i:03d}",
                    operation="replace",
                    chunk_id=f"chunk_{i}",
                    old_html=f"<p>old good {i}</p>",
                    new_html=f"<p>new good {i}</p>",
                    ai_explanation=f"Tightened wording in clause {i}.",
                ),
                should_approve=True,
                reason="Faithful rewrite, no semantic change.",
                error_kind=None,
                **CONFIRMED,
            )
        )
    for j in range(n_bad):
        out.append(
            LabelledChange(
                change=Change(
                    change_id=f"sd_change_{100 + j:03d}",
                    operation="replace",
                    chunk_id=f"chunk_{100 + j}",
                    old_html=f"<p>Payment due in 30 days ({j})</p>",
                    new_html=f"<p>Payment due in 90 days ({j})</p>",
                    ai_explanation="Clarified payment terms.",
                ),
                should_approve=False,
                reason="Silently changes a contractual number.",
                error_kind="wrong_number",
                **CONFIRMED,
            )
        )
    return out


def _walk_keys(obj) -> list[str]:
    """Every dict key anywhere in a nested structure."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            found.append(str(k))
            found.extend(_walk_keys(v))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_keys(item))
    return found


# -- GT-1 -----------------------------------------------------------------


def test_gt1_reviewer_view_never_contains_label_fields():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>doc</p>",
        labelled=_labelled(), seed=7,
    )
    view = build_reviewer_view(batch)
    blob = json.dumps(view)

    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in blob, f"GT-1 leak: {needle!r} present in reviewer view"

    keys = set(_walk_keys(view))
    assert not keys & set(FORBIDDEN_SUBSTRINGS), "GT-1 leak: forbidden key in view"


def test_gt1_whitelist_fails_closed_for_unknown_future_fields():
    """A field nobody thought to censor must not leak by default."""
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>doc</p>",
        labelled=_labelled(), seed=7,
    )
    # Simulate a future schema gaining an extra ground-truth-ish field.
    for record in batch["ground_truth"]:
        record["secret_future_field"] = "this must never be published"
    for change in batch["changes"]:
        change["secret_future_field"] = "nor this"

    view = build_reviewer_view(batch)
    blob = json.dumps(view)

    assert "secret_future_field" not in blob
    assert "this must never be published" not in blob
    served = {k for c in view["changes"] for k in c}
    assert served <= set(REVIEWER_VISIBLE_CHANGE_FIELDS), (
        f"GT-1: reviewer view served non-whitelisted fields: "
        f"{served - set(REVIEWER_VISIBLE_CHANGE_FIELDS)}"
    )


# -- GT-2 -----------------------------------------------------------------


def test_gt2_bad_changes_do_not_cluster_by_position():
    """Across many seeds, bad changes must land mid-distribution on average."""
    ranks: list[float] = []
    for seed in range(300):
        batch = build_batch(
            batch_id=f"b{seed}", document_id="doc1", document_html="<p>d</p>",
            labelled=_labelled(), seed=seed,
        )
        bad_ids = {
            r["change_id"] for r in batch["ground_truth"] if not r["should_approve"]
        }
        order = [c["source_change_id"] for c in batch["changes"]]
        n = len(order) - 1
        for cid in bad_ids:
            ranks.append(order.index(cid) / n)

    mean_rank = sum(ranks) / len(ranks)
    assert 0.40 < mean_rank < 0.60, (
        f"GT-2: seeded-bad changes cluster at normalized rank {mean_rank:.3f}; "
        "position is correlated with the label"
    )


def test_gt2_shuffle_is_deterministic_for_a_fixed_seed():
    kwargs = dict(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>", labelled=_labelled()
    )
    first = build_batch(seed=42, **kwargs)
    second = build_batch(seed=42, **kwargs)
    other = build_batch(seed=43, **kwargs)

    order_a = [c["source_change_id"] for c in first["changes"]]
    order_b = [c["source_change_id"] for c in second["changes"]]
    order_c = [c["source_change_id"] for c in other["changes"]]

    assert order_a == order_b, "GT-2: fixed seed must reproduce a fixed order"
    assert order_a != order_c, "GT-2: different seeds should differ (sanity check)"


# -- GT-3 -----------------------------------------------------------------


def test_gt3_reviewer_ids_are_opaque():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(), seed=11,
    )
    view = build_reviewer_view(batch)
    for change in view["changes"]:
        rid = change["id"]
        assert isinstance(rid, str) and len(rid) >= 8
        assert all(ch in "0123456789abcdef" for ch in rid), (
            f"GT-3: reviewer id {rid!r} is not opaque hex"
        )


def test_gt3_ids_do_not_change_when_labels_flip():
    """The strongest form of 'ids do not encode the label'.

    Same content and seed, inverted labels -> byte-identical reviewer view.
    If ids (or order) depended on the label in any way, this diverges.
    """
    labelled = _labelled()
    flipped = [
        LabelledChange(
            change=lc.change,
            should_approve=not lc.should_approve,
            reason="inverted for test",
            error_kind=None if not lc.should_approve else "wrong_number",
            **CONFIRMED,
        )
        for lc in labelled
    ]

    kwargs = dict(batch_id="b1", document_id="doc1", document_html="<p>d</p>", seed=99)
    view_a = build_reviewer_view(build_batch(labelled=labelled, **kwargs))
    view_b = build_reviewer_view(build_batch(labelled=flipped, **kwargs))

    assert json.dumps(view_a, sort_keys=True) == json.dumps(view_b, sort_keys=True), (
        "GT-3: reviewer view changed when only the labels changed"
    )


# -- GT-4 -----------------------------------------------------------------


def test_gt4_tampering_with_a_label_is_detected():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(), seed=3,
    )
    verify_ground_truth(batch)  # baseline: clean batch verifies

    batch["ground_truth"][0]["should_approve"] = not batch["ground_truth"][0][
        "should_approve"
    ]

    with pytest.raises(GroundTruthTampered):
        verify_ground_truth(batch)


def test_gt4_digest_ignores_key_order_but_not_values():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(), seed=3,
    )
    reordered = [
        dict(reversed(list(record.items()))) for record in batch["ground_truth"]
    ]
    assert ground_truth_digest(reordered) == ground_truth_digest(batch["ground_truth"])

    mutated = json.loads(json.dumps(batch["ground_truth"]))
    mutated[0]["reason"] = "revised after seeing the results"
    assert ground_truth_digest(mutated) != ground_truth_digest(batch["ground_truth"])


def test_gt4_batch_records_a_pre_registration_timestamp():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(), seed=3,
    )
    assert batch["pre_registered_at"], "GT-4: batch must carry a pre-registration time"
    assert batch["ground_truth_sha256"]


# -- GT-5 -----------------------------------------------------------------


def test_gt5_reviewer_view_reveals_no_base_rate():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(), seed=5,
    )
    view = build_reviewer_view(batch)
    keys = {k.lower() for k in _walk_keys(view)}

    for banned in ("n_bad", "bad_count", "n_should_reject", "base_rate", "error_rate"):
        assert banned not in keys, f"GT-5: reviewer view exposes {banned}"


def test_gt5_batches_vary_their_bad_count():
    """A constant base rate across batches is itself learnable."""
    batches = [
        build_batch(
            batch_id=f"b{i}", document_id=f"doc{i}", document_html="<p>d</p>",
            labelled=_labelled(n_good=4 + i, n_bad=2 + (i % 3)), seed=i,
        )
        for i in range(4)
    ]
    counts = {
        sum(1 for r in b["ground_truth"] if not r["should_approve"]) for b in batches
    }
    assert len(counts) > 1, "GT-5: every batch has the same number of bad changes"


# -- GT-7 -----------------------------------------------------------------


def test_gt7_unconfirmed_labels_cannot_be_pre_registered():
    """The invariant added after the pilot produced a wrong intent-derived label."""
    labelled = _labelled(n_good=2, n_bad=1)
    labelled[1] = LabelledChange(
        change=labelled[1].change,
        should_approve=labelled[1].should_approve,
        reason=labelled[1].reason,
        error_kind=labelled[1].error_kind,
    )  # no confirmation stamp

    with pytest.raises(UnconfirmedLabel) as exc:
        build_batch(
            batch_id="b1", document_id="doc1", document_html="<p>d</p>",
            labelled=labelled, seed=1,
        )
    assert labelled[1].change.change_id in str(exc.value)


def test_gt7_confirmation_records_who_and_when():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(n_good=1, n_bad=1), seed=1,
    )
    for record in batch["ground_truth"]:
        assert record["confirmed_by"] == "designer"
        assert record["confirmed_at"]


def test_gt7_an_overturned_intent_stays_visible():
    """A confirmation that flips the intent must not silently overwrite it.

    This is the exact pilot case: the intent said approve, the change that
    arrived deserved reject.
    """
    change = Change(
        change_id="chg_wordiness",
        operation="replace",
        chunk_id="c1",
        old_html="<p>The Vendor shall be responsible for performance.</p>",
        new_html="<p>The parties agree to the terms herein.</p>",
        ai_explanation="Made it concise.",
    )
    overturned = LabelledChange(
        change=change,
        should_approve=False,
        reason="Rewrite deletes the Vendor's performance obligation entirely.",
        error_kind="dropped_clause",
        intent_said_approve=True,
        **CONFIRMED,
    )
    assert overturned.overrides_intent is True

    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=[overturned] + _labelled(n_good=1, n_bad=0), seed=1,
    )
    record = next(r for r in batch["ground_truth"] if r["change_id"] == "chg_wordiness")
    assert record["should_approve"] is False
    assert record["overrode_intent"] is True


def test_gt7_confirmation_provenance_is_covered_by_the_tamper_digest():
    """Rewriting who confirmed a label must trip GT-4, like any other edit."""
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(n_good=1, n_bad=1), seed=1,
    )
    verify_ground_truth(batch)

    batch["ground_truth"][0]["confirmed_by"] = "someone_else"
    with pytest.raises(GroundTruthTampered):
        verify_ground_truth(batch)


# -- GT-6 -----------------------------------------------------------------


def test_gt6_decision_event_carries_no_ground_truth():
    event = make_decision_event(
        reviewer_id="R1",
        batch_id="b1",
        condition="batch_section",
        reviewer_change_id="a1b2c3d4",
        decision="approve",
        shown_at="2026-08-14T10:00:00+00:00",
        decided_at="2026-08-14T10:00:07+00:00",
    )
    blob = json.dumps(event)
    for needle in FORBIDDEN_SUBSTRINGS:
        assert needle not in blob, f"GT-6: event log leaks {needle!r}"
    assert "correct" not in event and "is_error" not in event


def test_gt6_scoring_works_by_join_not_by_denormalization():
    batch = build_batch(
        batch_id="b1", document_id="doc1", document_html="<p>d</p>",
        labelled=_labelled(n_good=2, n_bad=2), seed=13,
    )
    view = build_reviewer_view(batch)

    # Reviewer approves everything; correct on the good ones only.
    events = [
        make_decision_event(
            reviewer_id="R1",
            batch_id="b1",
            condition="batch_section",
            reviewer_change_id=c["id"],
            decision="approve",
            shown_at="2026-08-14T10:00:00+00:00",
            decided_at="2026-08-14T10:00:05+00:00",
        )
        for c in view["changes"]
    ]

    scored = score_decisions(events, batch)
    assert sum(1 for s in scored if s["correct"]) == 2
    assert sum(1 for s in scored if not s["correct"]) == 2
