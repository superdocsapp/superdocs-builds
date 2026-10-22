"""corpus_builder tests. No API key, no network.

The fixture in tests/fixtures/job_doc01.json is a realistic job payload shaped
exactly like the documented JobResponse, so the whole build path -- extract,
match, label, digest, write -- runs offline.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import corpus_builder as cb  # noqa: E402
from corpus.edit_specs import DOC01  # noqa: E402
from ground_truth import (  # noqa: E402
    REVIEWER_VISIBLE_CHANGE_FIELDS,
    build_reviewer_view,
    verify_ground_truth,
)
from superdocs_client import BudgetExceeded, SuperDocsError, Usage  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "job_doc01.json"


@pytest.fixture
def job() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def changes(job) -> list[dict]:
    from superdocs_client import SuperDocsClient

    return SuperDocsClient.extract_pending_changes(job)


def _confirmations_for(job: dict, *, agree_with_intent: bool = True) -> dict:
    """Stand in for the human GT-7 confirmation step.

    Defaults to agreeing with every intent, which is what makes the rest of the
    build path testable; the disagreement case is tested explicitly.
    """
    result = cb.match_changes_to_intents(cb.merge_changes([job]), DOC01.intents)
    return {
        lc.change.change_id: {
            "change_id": lc.change.change_id,
            "should_approve": lc.should_approve if agree_with_intent else not lc.should_approve,
            "reason": lc.reason,
            "error_kind": lc.error_kind,
            "confirmed_by": "test-designer",
            "confirmed_at": "2026-08-14T10:00:00+00:00",
        }
        for lc in result.labelled
    }


@pytest.fixture
def confirmations(job) -> dict:
    return _confirmations_for(job)


# -- spec hygiene ---------------------------------------------------------


def test_every_marker_appears_exactly_once_in_the_document():
    """An ambiguous marker would silently mislabel a change."""
    html = DOC01.html
    for intent in DOC01.intents:
        count = html.count(intent.old_marker)
        assert count == 1, (
            f"marker for {intent.key!r} appears {count} times in doc01; "
            "markers must be unique to match reliably"
        )


def test_intents_have_unique_keys_and_a_mixed_base_rate():
    keys = [i.key for i in DOC01.intents]
    assert len(keys) == len(set(keys))

    bad = [i for i in DOC01.intents if not i.should_approve]
    good = [i for i in DOC01.intents if i.should_approve]
    assert bad and good, "a batch needs both good and bad changes to be informative"
    assert all(i.error_kind for i in bad), "every bad intent needs an error_kind"
    assert all(i.error_kind is None for i in good), "good intents must not carry an error_kind"


def test_study_documents_have_realistic_base_rates():
    """doc01 ended up 5-bad-of-7; a reviewer could win by rejecting everything."""
    from corpus.edit_specs import STUDY_DOCUMENTS

    assert len(STUDY_DOCUMENTS) == 4, "the 2x2 needs one document per condition"
    for spec in STUDY_DOCUMENTS:
        bad = sum(1 for i in spec.intents if not i.should_approve)
        assert 1 <= bad <= 2, f"{spec.doc_id} seeds {bad} bad changes; want 1-2"
        assert bad / len(spec.intents) < 0.35, f"{spec.doc_id} base rate too high"


def test_study_documents_vary_their_base_rate():
    """A constant ratio is learnable across conditions (GT-5)."""
    from corpus.edit_specs import STUDY_DOCUMENTS

    counts = {sum(1 for i in s.intents if not i.should_approve) for s in STUDY_DOCUMENTS}
    assert len(counts) > 1, f"every study document seeds the same number of bad changes: {counts}"


def test_study_document_markers_are_unique():
    """An ambiguous marker mislabels a change, and finding out costs an operation."""
    from corpus.edit_specs import STUDY_DOCUMENTS

    for spec in STUDY_DOCUMENTS:
        html = spec.html
        for intent in spec.intents:
            assert html.count(intent.old_marker) == 1, (
                f"{spec.doc_id}/{intent.key}: marker appears "
                f"{html.count(intent.old_marker)} times"
            )


def test_deletion_of_a_protective_clause_is_no_longer_seeded():
    """SuperDocs refused it twice, producing no-ops (PROGRESS.md A11)."""
    from corpus.edit_specs import STUDY_DOCUMENTS

    for spec in STUDY_DOCUMENTS:
        for intent in spec.intents:
            assert intent.error_kind != "dropped_clause", (
                f"{spec.doc_id}/{intent.key} seeds an error type the API will not perform"
            )
            assert "delete the entire" not in intent.instruction.lower()


def test_study_documents_are_not_excluded_and_doc01_is():
    from corpus.edit_specs import DOC01, STUDY_DOCUMENTS

    assert DOC01.exclude_from_study is True
    assert all(not s.exclude_from_study for s in STUDY_DOCUMENTS)


def test_bad_intents_cover_the_planned_error_taxonomy():
    """PLAN.md.pdf section 3 names four failure modes; doc01 seeds all four."""
    kinds = {i.error_kind for i in DOC01.intents if not i.should_approve}
    assert kinds == {"wrong_number", "dropped_clause", "meaning_flip", "lossy_merge"}


def test_build_message_lists_every_intent():
    message = DOC01.build_message()
    assert message.count("\n") >= len(DOC01.intents)
    for i, _ in enumerate(DOC01.intents, start=1):
        assert f"{i}." in message


# -- matching -------------------------------------------------------------


def test_all_eight_intents_match_the_fixture(changes):
    result = cb.match_changes_to_intents(changes, DOC01.intents)
    assert len(result.labelled) == 8
    assert result.missing == []
    assert result.unmatched == []


def test_matching_assigns_the_right_label_to_the_right_change(changes):
    result = cb.match_changes_to_intents(changes, DOC01.intents)
    by_id = {lc.change.change_id: lc for lc in result.labelled}

    assert by_id["chg_05_payment_terms"].should_approve is False
    assert by_id["chg_05_payment_terms"].error_kind == "wrong_number"
    assert by_id["chg_06_liability_cap"].error_kind == "dropped_clause"
    assert by_id["chg_07_termination"].error_kind == "meaning_flip"
    assert by_id["chg_08_merge_dp"].error_kind == "lossy_merge"

    assert by_id["chg_02_typo_receive"].should_approve is True
    assert by_id["chg_02_typo_receive"].error_kind is None


def test_a_deletion_is_matched_from_old_html_alone(changes):
    """new_html is null for a delete, so the marker must be found on the old side."""
    deletion = next(c for c in changes if c["operation"] == "delete")
    assert deletion["new_html"] is None
    result = cb.match_changes_to_intents([deletion], DOC01.intents)
    assert len(result.labelled) == 1
    assert result.labelled[0].error_kind == "dropped_clause"


def test_unrequested_changes_are_never_auto_labelled():
    """The core honesty property of the matcher."""
    rogue = {
        "change_id": "chg_99_rogue",
        "operation": "replace",
        "chunk_id": "chunk_0099",
        "old_html": "<p>Some clause we never asked about.</p>",
        "new_html": "<p>Something else entirely.</p>",
        "ai_explanation": "Improved clarity.",
    }
    result = cb.match_changes_to_intents([rogue], DOC01.intents)

    assert result.labelled == [], "a change we did not request must not enter the answer key"
    assert len(result.unmatched) == 1
    assert result.unmatched[0]["change_id"] == "chg_99_rogue"
    assert len(result.missing) == len(DOC01.intents)


def test_intents_not_performed_are_reported_as_missing(changes):
    subset = [c for c in changes if c["change_id"] != "chg_05_payment_terms"]
    result = cb.match_changes_to_intents(subset, DOC01.intents)

    assert "b_payment_days" in result.missing
    assert len(result.labelled) == 7


def test_one_intent_cannot_be_claimed_twice(changes):
    """Two changes touching one marker must not both inherit the same label."""
    target = next(c for c in changes if c["change_id"] == "chg_05_payment_terms")
    duplicate = dict(target, change_id="chg_05_again")
    result = cb.match_changes_to_intents([target, duplicate], DOC01.intents)

    assert len(result.labelled) == 1
    assert [c["change_id"] for c in result.unmatched] == ["chg_05_again"]


# -- checkpointing --------------------------------------------------------


def test_checkpoint_roundtrip_and_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "REPO", tmp_path)

    assert cb.load_checkpoint("docX") is None
    cb.save_checkpoint("docX", {"job_id": "j1", "status": "awaiting_approval"})

    assert cb.load_checkpoint("docX")["job_id"] == "j1"
    assert not list((tmp_path / "cp").glob("*.tmp")), "no temp file may survive the write"


def test_corrupt_checkpoint_is_ignored_not_fatal(tmp_path, monkeypatch):
    cp = tmp_path / "cp"
    cp.mkdir()
    (cp / "docX.job.json").write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(cb, "CHECKPOINTS", cp)

    assert cb.load_checkpoint("docX") is None


def test_checkpoint_is_reused_without_a_client(tmp_path, monkeypatch, job, confirmations):
    """Proves a restart re-spends nothing: no client, and it still builds."""
    cp = tmp_path / "cp"
    monkeypatch.setattr(cb, "CHECKPOINTS", cp)
    monkeypatch.setattr(cb, "REPO", tmp_path)
    cb.save_checkpoint("doc01", job)

    # client=None: any API call would crash
    batch = cb.build_document(None, DOC01, confirmations=confirmations)
    assert len(batch["changes"]) == 8


# -- build_document end to end (offline) ---------------------------------


def test_offline_build_produces_a_verifiable_batch(confirmations):
    batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)

    verify_ground_truth(batch)
    assert batch["batch_id"] == "batch_doc01"
    assert len(batch["changes"]) == 8
    assert len(batch["ground_truth"]) == 8
    assert sum(1 for r in batch["ground_truth"] if not r["should_approve"]) == 4
    assert batch["build_report"]["intents_matched"] == 8
    assert batch["build_report"]["missing_intents"] == []


def test_built_batch_reviewer_view_leaks_nothing(confirmations):
    """GT-1 again, on real built output rather than a synthetic fixture.

    Checks keys structurally and label *values* literally. A bare substring
    scan is useless here: the contract itself contains 'unreasonably', which
    trivially matches a search for 'reason'.
    """
    batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
    view = build_reviewer_view(batch)
    blob = json.dumps(view)

    def all_keys(obj) -> set[str]:
        if isinstance(obj, dict):
            return set(obj) | {k for v in obj.values() for k in all_keys(v)}
        if isinstance(obj, list):
            return {k for item in obj for k in all_keys(item)}
        return set()

    leaked = all_keys(view) & {
        "should_approve", "error_kind", "reason", "ground_truth",
        "source_change_id", "ground_truth_sha256", "build_report", "seed",
    }
    assert not leaked, f"leak: ground-truth keys in reviewer view: {leaked}"

    # The rationales themselves are distinctive prose; none may appear verbatim.
    for record in batch["ground_truth"]:
        assert record["reason"] not in blob, f"leak: rationale for {record['change_id']}"
        if record["error_kind"]:
            assert record["error_kind"] not in blob

    for change in view["changes"]:
        assert set(change) <= set(REVIEWER_VISIBLE_CHANGE_FIELDS)
        assert change["new_html"] is not None or change["operation"] == "delete"


def test_build_raises_when_no_changes_come_back(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"status": "completed", "metadata": {}}), encoding="utf-8")

    with pytest.raises(SuperDocsError, match="no pending changes"):
        cb.build_document(None, DOC01, offline=empty)


# -- warm-up ------------------------------------------------------------


class _StubClient:
    """Minimal stand-in; warm_up only needs these two methods."""

    def __init__(self, raise_with=None):
        self.raise_with = raise_with
        self.calls: list[str] = []

    def chat_async(self, **kwargs):
        self.calls.append("chat_async")
        if self.raise_with:
            raise self.raise_with
        return "job_warm"

    def poll_job(self, job_id, **kwargs):
        self.calls.append("poll_job")
        return {"status": "completed"}


def test_warmup_swallows_a_cold_start_failure():
    """A failed warm-up is the anticipated case, not an error (PROGRESS.md A6)."""
    client = _StubClient(raise_with=SuperDocsError("504 gateway timeout"))
    cb.warm_up(client)  # must not raise
    assert client.calls == ["chat_async"]


def test_warmup_still_stops_on_budget_exhaustion():
    """Budget refusal must never be mistaken for a tolerable cold start."""
    client = _StubClient(raise_with=BudgetExceeded("over the cap"))
    with pytest.raises(BudgetExceeded):
        cb.warm_up(client)


def test_warmup_succeeds_quietly_when_backend_is_warm():
    client = _StubClient()
    cb.warm_up(client)
    assert client.calls == ["chat_async", "poll_job"]


def test_no_warmup_when_every_document_is_already_checkpointed(
    tmp_path, monkeypatch, job, confirmations, capsys
):
    """Regression: a rerun over checkpoints burned a real operation on warm-up."""
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "STUDY_DATA", tmp_path)
    monkeypatch.setattr(cb, "BATCHES_PATH", tmp_path / "batches.json")
    monkeypatch.setattr(cb, "REPO", tmp_path)
    cb.save_checkpoint("doc01", job)
    (tmp_path / "confirmations.json").write_text(
        json.dumps({"confirmations": list(confirmations.values())}), encoding="utf-8"
    )

    real_client = cb.SuperDocsClient

    class NoCallsClient:
        # keep the real parser: merge_changes calls it as a static method
        extract_pending_changes = staticmethod(real_client.extract_pending_changes)
        ops_used = 0

        def __init__(self, **kwargs):
            pass

        def verify_key(self):
            return True

        def chat_async(self, **kwargs):
            raise AssertionError("no operation may be spent on a checkpointed rerun")

    monkeypatch.setattr(cb, "SuperDocsClient", NoCallsClient)
    monkeypatch.setattr(cb, "LEDGER_PATH", tmp_path / "ops.jsonl")
    monkeypatch.setattr(cb, "load_dotenv", lambda *a, **kw: None)

    assert cb.main(["--mode", "pilot"]) == 0
    assert "warmup] skipped" in capsys.readouterr().out


# -- main() wiring -------------------------------------------------------


def test_main_offline_writes_batches_json(tmp_path, monkeypatch, capsys, confirmations):
    monkeypatch.setattr(cb, "STUDY_DATA", tmp_path)
    monkeypatch.setattr(cb, "BATCHES_PATH", tmp_path / "batches.json")
    monkeypatch.setattr(cb, "REPO", tmp_path)
    (tmp_path / "confirmations.json").write_text(
        json.dumps({"confirmations": list(confirmations.values())}), encoding="utf-8"
    )

    code = cb.main(["--mode", "pilot", "--offline", str(FIXTURE)])
    assert code == 0

    payload = json.loads((tmp_path / "batches.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "pilot"
    assert payload["ops_spent"] == 0, "offline replay must spend nothing"
    assert len(payload["batches"]) == 1
    verify_ground_truth(payload["batches"][0])

    assert "TOTAL SPENT THIS RUN: 0/5" in capsys.readouterr().out


# -- GT-7 at the builder level -------------------------------------------


def test_build_refuses_unconfirmed_labels():
    """Intent labels alone must not produce a pre-registered batch."""
    from ground_truth import UnconfirmedLabel

    with pytest.raises(UnconfirmedLabel):
        cb.build_document(None, DOC01, offline=FIXTURE, confirmations={})


def test_a_confirmation_can_overturn_the_intent(job):
    """The pilot case: intent said approve, the real change deserved reject."""
    confirmations = _confirmations_for(job)
    target = "chg_01_scope_concise"
    confirmations[target] = {
        **confirmations[target],
        "should_approve": False,
        "error_kind": "dropped_clause",
        "reason": "Rewrite deletes the Vendor's performance obligation.",
    }

    batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
    record = next(r for r in batch["ground_truth"] if r["change_id"] == target)

    assert record["should_approve"] is False
    assert record["overrode_intent"] is True
    assert target in batch["build_report"]["labels_overriding_intent"]


def test_unconfirmed_unmatched_changes_are_excluded_not_guessed(job, confirmations):
    rogue = {
        "change_id": "chg_99_rogue",
        "operation": "edit",
        "chunk_id": "c99",
        "old_html": "<p>Untouched clause.</p>",
        "new_html": "<p>Rewritten clause.</p>",
        "ai_explanation": "Improved clarity.",
    }
    job["metadata"]["pending_changes"].append(rogue)

    result = cb.match_changes_to_intents(cb.merge_changes([job]), DOC01.intents)
    assert [c["change_id"] for c in result.unmatched] == ["chg_99_rogue"]


def test_a_confirmation_for_an_unknown_change_id_is_reported(tmp_path, monkeypatch, job):
    """Caught for real: a mistyped id would silently drop a confirmed label."""
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "REPO", tmp_path)
    cb.save_checkpoint("doc01", job)

    orphans = cb.check_orphan_confirmations(
        {"chg_does_not_exist": {}, "chg_01_scope_concise": {}}, (DOC01,)
    )
    assert orphans == ["chg_does_not_exist"]


def test_confirmations_for_other_documents_do_not_block_a_build(job, confirmations):
    """Regression: the orphan guard fired on doc01's labels while building doc02.

    The confirmations file is global, so most of its entries belong to other
    documents. Narrowing must happen per-document.
    """
    confirmations["chg_belongs_to_another_doc"] = {
        "change_id": "chg_belongs_to_another_doc",
        "should_approve": False,
        "reason": "labelled on a different document",
        "error_kind": "wrong_number",
        "confirmed_by": "test-designer",
        "confirmed_at": "2026-08-14T10:00:00+00:00",
    }

    batch = cb.build_document(None, DOC01, offline=FIXTURE, confirmations=confirmations)
    assert len(batch["changes"]) == 8
    assert "chg_belongs_to_another_doc" not in [
        r["change_id"] for r in batch["ground_truth"]
    ]


# -- no-op filtering ------------------------------------------------------


def test_noop_detection():
    """Live pilot returned two of these; they must never reach a reviewer."""
    assert cb.is_noop({"operation": "edit", "old_html": "<p>Same</p>", "new_html": "<p>Same</p>"})
    assert cb.is_noop(
        {"operation": "edit", "old_html": "<p>Same  text</p>", "new_html": "<p>Same text</p>"}
    ), "whitespace-only differences are still no-ops"
    assert not cb.is_noop({"operation": "edit", "old_html": "<p>A</p>", "new_html": "<p>B</p>"})


def test_a_deletion_is_never_a_noop():
    """new_html is null for a delete; removing content is a real change."""
    assert not cb.is_noop(
        {"operation": "delete", "old_html": "<p>Liability cap</p>", "new_html": None}
    )


def test_noops_are_dropped_before_labelling(job, confirmations):
    job["metadata"]["pending_changes"].append(
        {
            "change_id": "chg_noop",
            "operation": "edit",
            "chunk_id": "c50",
            "old_html": "<p>Unchanged clause.</p>",
            "new_html": "<p>Unchanged clause.</p>",
            "ai_explanation": "Refined wording.",
        }
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(job, fh)
        path = Path(fh.name)

    batch = cb.build_document(None, DOC01, offline=path, confirmations=confirmations)
    assert batch["build_report"]["noops_dropped"] == 1
    assert "chg_noop" not in [c["source_change_id"] for c in batch["changes"]]


# -- multi-call documents -------------------------------------------------


def test_merge_changes_dedupes_across_jobs(job):
    """The same change arriving in two checkpoints must not double-count."""
    merged = cb.merge_changes([job, job])
    assert len(merged) == 8


def test_merge_changes_combines_distinct_jobs(job):
    first = json.loads(json.dumps(job))
    first["metadata"]["pending_changes"] = first["metadata"]["pending_changes"][:5]

    second = json.loads(json.dumps(job))
    second["metadata"]["pending_changes"] = second["metadata"]["pending_changes"][5:]

    merged = cb.merge_changes([first, second])
    assert len(merged) == 8
    assert cb.match_changes_to_intents(merged, DOC01.intents).missing == []


def test_load_all_checkpoints_picks_up_follow_up_slots(tmp_path, monkeypatch, job):
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "REPO", tmp_path)

    cb.save_checkpoint("doc01", job)
    cb.save_checkpoint("doc01", job, slot="b")

    assert len(cb.load_all_checkpoints("doc01")) == 2
    assert (tmp_path / "cp" / "doc01_b.job.json").exists()


def test_fill_missing_requests_only_the_skipped_intents(tmp_path, monkeypatch, job):
    """Mirrors the live pilot: 5 of 8 landed, so 3 must be re-requested."""
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "REPO", tmp_path)

    partial = json.loads(json.dumps(job))
    partial["metadata"]["pending_changes"] = [
        c for c in partial["metadata"]["pending_changes"]
        if c["change_id"] not in {"chg_02_typo_receive", "chg_06_liability_cap", "chg_08_merge_dp"}
    ]
    cb.save_checkpoint("doc01", partial)

    asked: dict = {}

    class Recorder:
        def chat_async(self, **kwargs):
            asked.update(kwargs)
            return "job_followup"

        def poll_job(self, job_id, **kwargs):
            return {"job_id": job_id, "status": "awaiting_approval", "metadata": {}}

    cb.fill_missing_intents(Recorder(), DOC01)

    message = asked["message"]
    assert "recieve" in message
    assert "150%" in message
    assert "Merge Clause 6" in message
    # and nothing about the five that already succeeded
    assert "hereby agreed and understood" not in message
    assert "thirty (30) days to ninety (90)" not in message
    assert asked["session_id"].endswith("_b"), "follow-up must use a fresh session"


def test_fill_missing_is_a_no_op_when_nothing_is_missing(tmp_path, monkeypatch, job):
    monkeypatch.setattr(cb, "CHECKPOINTS", tmp_path / "cp")
    monkeypatch.setattr(cb, "REPO", tmp_path)
    cb.save_checkpoint("doc01", job)

    class Exploder:
        def chat_async(self, **kwargs):
            raise AssertionError("must not spend an operation when nothing is missing")

    cb.fill_missing_intents(Exploder(), DOC01)


def test_main_defaults_to_the_pilot_cap_of_five(monkeypatch, tmp_path):
    """The <=5 pilot cap from PLAN.md.pdf section 6 must be the default."""
    assert cb.PILOT_OPS_CAP == 5
    assert cb.FULL_OPS_CAP == 15
