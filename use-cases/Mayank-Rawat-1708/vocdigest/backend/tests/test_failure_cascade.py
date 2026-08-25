"""
@file: backend/tests/test_failure_cascade.py
@description: Tests the one rule that ties three bugs together: empty or failed output
    must never travel onward as though it were valid. A stage that fails has to stop the
    run; a stage whose required input is missing has to say so rather than quietly
    producing nothing; and an approval gate with nothing in it has to fail rather than
    pause, because a pause invites a human to resolve something that has no resolution.
@flow: break one stage -> assert the run is FAILED, that nothing downstream of it
    checkpointed, and that the reason names the real cause -> then assert the same holds
    across a resume, and via the operator skip endpoint, which is how the original
    cascade actually got past a failed extract.
@dependencies: conftest fixtures (test_db, fake_groq, fake_superdocs, sample_csv)
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.agents.state import STAGES
from backend.db.database import session_scope
from backend.models import ApprovalItem, Conversation, Run, RunStatus, Theme
from backend.services.groq_client import GroqError

pytestmark = pytest.mark.asyncio


async def _stages(run_uuid) -> dict:
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        return dict((run.checkpoint_data or {}).get("stages") or {})


async def _run_row(run_uuid) -> Run:
    async with session_scope() as session:
        return await session.get(Run, run_uuid)


async def _decisions(run_uuid) -> list[dict]:
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        return list(run.decision_log or [])


# ------------------------------------------------- a failed stage halts the run


async def test_failed_stage_halts_the_run_with_no_downstream_checkpoints(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """A 413 in extract must stop the run, not walk the pipeline on empty input.

    This is the exact shape of the reported failure: extract failed, and clustering,
    anonymization, comparison, drafting and the approval gate all ran anyway on nothing,
    arriving at AWAITING_APPROVAL with zero themes and zero items to decide.
    """
    run_uuid = await create_run(str(sample_csv), None)

    # A plain GroqError is what a 413 becomes once retries are exhausted: not an outage,
    # so it must not divert to the heuristic fallback.
    fake_groq.fail_with = None

    # Let classify succeed, then fail extract specifically.
    original = fake_groq.complete_json

    async def _fail_extract(self, system_prompt, user_prompt, **kwargs):
        if "extract structured facts" in system_prompt:
            raise GroqError(
                "Groq 413: Request too large ... tokens per minute (TPM): "
                "Limit 8000, Requested 9904"
            )
        return await original(self, system_prompt, user_prompt, **kwargs)

    fake_groq.complete_json = _fail_extract
    try:
        result = await execute_run(run_uuid)
    finally:
        fake_groq.complete_json = original

    assert result["paused"] is False, "a failed run must not report itself as paused"

    run = await _run_row(run_uuid)
    assert run.status == RunStatus.FAILED, f"expected FAILED, got {run.status}"
    assert "extract" in (run.error_message or "").lower()

    stages = await _stages(run_uuid)
    assert stages["extract"]["status"] == "FAILED"
    for later in ("theme", "anonymize", "compare", "draft", "human_gate", "superdocs"):
        assert later not in stages, (
            f"{later} checkpointed after extract failed — a failed stage must stop the "
            f"pipeline, not hand it an empty result"
        )

    # And nothing downstream left rows behind either.
    async with session_scope() as session:
        themes = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid)))
            .scalars()
        )
        items = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        )
    assert themes == [], "themes were created from a failed extract"
    assert items == [], "approval items were created from a failed extract"


async def test_resuming_a_failed_run_does_not_walk_past_the_failure(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """The halt has to survive a resume, not just the invocation that failed.

    Resume re-enters the same linear chain. Without an explicit dependency check the
    stage after the failed one is perfectly willing to run again on the same nothing.
    """
    run_uuid = await create_run(str(sample_csv), None)
    original = fake_groq.complete_json

    async def _fail_extract(self, system_prompt, user_prompt, **kwargs):
        if "extract structured facts" in system_prompt:
            raise GroqError("Groq 413: Request too large")
        return await original(self, system_prompt, user_prompt, **kwargs)

    fake_groq.complete_json = _fail_extract
    try:
        await execute_run(run_uuid)
        # Resume while extract is still FAILED.
        result = await execute_run(run_uuid)
    finally:
        fake_groq.complete_json = original

    run = await _run_row(run_uuid)
    assert run.status == RunStatus.FAILED
    assert result["paused"] is False

    stages = await _stages(run_uuid)
    for later in ("theme", "anonymize", "draft", "human_gate"):
        assert later not in stages, f"{later} ran on a resume despite extract FAILED"


async def test_a_stage_refuses_to_run_when_its_dependency_was_skipped(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """An operator skip must not launder a failure into apparent success.

    In the real run this is how the cascade got moving: extract 413'd, an operator
    skipped it from the run view, and the SKIPPED checkpoint read to every later stage
    exactly like a completed one.
    """
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)  # runs to the gate normally

    # Wipe theme onwards, and rewrite extract as SKIPPED — precisely what the skip
    # endpoint used to be willing to do.
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        for stage in STAGES[STAGES.index("theme"):]:
            stages.pop(stage, None)
        stages["extract"] = {
            "stage": "extract",
            "status": "SKIPPED",
            "result": {"state_delta": {}},
            "started_at": None,
            "completed_at": None,
            "error": None,
            "attempts": 1,
        }
        data["stages"] = stages
        run.checkpoint_data = data
        run.status = RunStatus.PENDING
        run.error_message = None
    # Clear the embeddings extract would have produced, so theme genuinely has no input.
    async with session_scope() as session:
        convs = list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        )
        for conv in convs:
            conv.embedding = None
            conv.theme_id = None

    result = await execute_run(run_uuid)

    run = await _run_row(run_uuid)
    assert run.status == RunStatus.FAILED, (
        "theme ran on a skipped extract instead of refusing"
    )
    assert result["paused"] is False

    decisions = [d["decision"] for d in await _decisions(run_uuid)]
    assert "BLOCKED_UPSTREAM" in decisions, (
        "the refusal must be recorded, naming the upstream stage responsible"
    )
    blocked = next(
        d for d in await _decisions(run_uuid) if d["decision"] == "BLOCKED_UPSTREAM"
    )
    assert "extract" in blocked["reason"]


async def test_required_stages_cannot_be_skipped_by_an_operator(
    test_db, api_client, fake_groq, fake_superdocs, sample_csv
):
    """The skip endpoint refuses any stage another stage's output is built from."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    for stage in ("ingest", "classify", "extract", "theme", "draft", "human_gate"):
        response = await api_client.post(
            f"/runs/{run_uuid}/stages/skip", json={"stage": stage}
        )
        assert response.status_code == 409, f"{stage} should be unskippable"
        assert "cannot be skipped" in response.json()["detail"]

    # Genuinely optional stages are still skippable: nothing is built from their output.
    for stage in ("compare", "anonymize"):
        response = await api_client.post(
            f"/runs/{run_uuid}/stages/skip", json={"stage": stage}
        )
        assert response.status_code == 202, f"{stage} should remain skippable"


# ------------------------------------------------- an empty input is not a skip


async def test_extract_with_no_relevant_conversations_fails_rather_than_skipping(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Nothing to extract is a run with no subject, not a stage with no work."""
    run_uuid = await create_run(str(sample_csv), None)

    original = fake_groq.complete_json

    async def _reject_everything(self, system_prompt, user_prompt, **kwargs):
        payload, usage, injected = await original(
            self, system_prompt, user_prompt, **kwargs
        )
        if "classify customer-support records" in system_prompt:
            for item in payload["results"]:
                item["relevant"] = False
                item["type"] = "marketing"
        return payload, usage, injected

    fake_groq.complete_json = _reject_everything
    try:
        result = await execute_run(run_uuid)
    finally:
        fake_groq.complete_json = original

    run = await _run_row(run_uuid)
    assert run.status == RunStatus.FAILED
    assert result["paused"] is False

    stages = await _stages(run_uuid)
    assert stages["extract"]["status"] == "FAILED"
    assert "nothing to analyse" in (run.error_message or "").lower()
    assert "human_gate" not in stages


async def test_a_missing_input_is_not_retried(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """An absent input will not appear on a second attempt, so do not spend three."""
    run_uuid = await create_run(str(sample_csv), None)
    original = fake_groq.complete_json

    async def _reject_everything(self, system_prompt, user_prompt, **kwargs):
        payload, usage, injected = await original(
            self, system_prompt, user_prompt, **kwargs
        )
        if "classify customer-support records" in system_prompt:
            for item in payload["results"]:
                item["relevant"] = False
        return payload, usage, injected

    fake_groq.complete_json = _reject_everything
    try:
        await execute_run(run_uuid)
    finally:
        fake_groq.complete_json = original

    stages = await _stages(run_uuid)
    assert stages["extract"]["attempts"] == 1, (
        f"extract retried an input that cannot appear: "
        f"{stages['extract']['attempts']} attempts"
    )


# ------------------------------------------------- the empty approval gate


async def test_gate_with_nothing_to_review_fails_instead_of_pausing(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Zero approval items is not a valid gate state.

    The old code asked "do items already exist?" to decide whether to create them. When
    zero were created that answer stayed false forever, so every re-entry created zero
    again and paused again — never progressing, never failing, and impossible to resolve
    from the UI, which showed "0 approved, 0 rejected" and no controls.
    """
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)  # reach the gate normally, with real items

    # Now reproduce the empty gate: keep draft COMPLETE but remove everything the gate
    # would build items from, then re-enter it.
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        stages.pop("human_gate", None)
        # An empty draft with no themes is what the gate saw in the reported run.
        stages["draft"] = {
            **stages["draft"],
            "result": {"state_delta": {"draft_sections": {}}},
        }
        data["stages"] = stages
        # The persisted state carries draft_sections too.
        state = dict(data.get("state") or {})
        state["draft_sections"] = {}
        data["state"] = state
        run.checkpoint_data = data
        run.status = RunStatus.PENDING
        run.error_message = None

    async with session_scope() as session:
        for row in list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        ):
            await session.delete(row)
        for conv in list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        ):
            conv.theme_id = None
        for theme in list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid)))
            .scalars()
        ):
            await session.delete(theme)

    before = len(await _decisions(run_uuid))
    result = await execute_run(run_uuid)

    run = await _run_row(run_uuid)
    assert run.status == RunStatus.FAILED, (
        f"an empty gate must fail, not pause; got {run.status}"
    )
    assert result["paused"] is False
    assert run.status != RunStatus.AWAITING_APPROVAL

    reason = (run.error_message or "").lower()
    assert "nothing to review" in reason, f"unclear failure message: {reason!r}"

    new_decisions = [d["decision"] for d in (await _decisions(run_uuid))[before:]]
    assert "GATE_OPENED" not in new_decisions, (
        f"the gate reported itself as opened while holding nothing: {new_decisions}"
    )
    assert "PAUSED" not in new_decisions, "an unresolvable gate must not pause"


async def test_empty_gate_cannot_loop_across_repeated_resumes(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Re-entering an unresolvable gate must not re-pause it. The ×6 in the report."""
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        data = dict(run.checkpoint_data or {})
        stages = dict(data.get("stages") or {})
        stages.pop("human_gate", None)
        # load_state replays each completed stage's delta, so the draft's own checkpoint
        # has to be emptied too or draft_sections comes straight back.
        stages["draft"] = {
            **stages["draft"],
            "result": {"state_delta": {"draft_sections": {}}},
        }
        data["stages"] = stages
        state = dict(data.get("state") or {})
        state["draft_sections"] = {}
        data["state"] = state
        run.checkpoint_data = data
        run.status = RunStatus.PENDING

    async with session_scope() as session:
        for row in list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        ):
            await session.delete(row)
        for conv in list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        ):
            conv.theme_id = None
        for theme in list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid)))
            .scalars()
        ):
            await session.delete(theme)

    paused_count = 0
    for _ in range(4):
        result = await execute_run(run_uuid)
        if result["paused"]:
            paused_count += 1
        async with session_scope() as session:
            run = await session.get(Run, run_uuid)
            run.status = RunStatus.PENDING  # simulate an operator hitting resume again

    assert paused_count == 0, (
        f"the gate paused {paused_count} time(s) with nothing to approve — this is the "
        f"infinite re-entry loop"
    )


# ------------------------------------------------- doing nothing should cost nothing


async def test_compare_short_circuits_when_there_are_no_themes(
    test_db, fake_groq, fake_superdocs, sample_csv, prior_digest
):
    """Comparison with one side empty must not call the model at all.

    In the reported run compare took 77.6 seconds while producing nothing: it read the
    prior digest and burned three attempts plus backoff on a doomed request, even though
    this quarter had zero themes to match anything against.
    """
    from backend.agents.nodes.compare import CompareNode
    from backend.agents.nodes.base import NodeSkip

    run_uuid = await create_run(str(sample_csv), str(prior_digest))
    await execute_run(run_uuid)

    async with session_scope() as session:
        for conv in list(
            (
                await session.execute(
                    select(Conversation).where(Conversation.run_id == run_uuid)
                )
            ).scalars()
        ):
            conv.theme_id = None
        for theme in list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid)))
            .scalars()
        ):
            await session.delete(theme)

    fake_groq.calls = []
    state = await load_state(run_uuid)
    node = CompareNode()
    with pytest.raises(NodeSkip) as excinfo:
        await node.run(state, run_uuid)

    assert "no themes" in str(excinfo.value).lower()
    assert fake_groq.calls == [], (
        "compare called the model with nothing to compare against"
    )


async def test_rerunning_theme_replaces_its_themes_rather_than_adding_more(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """A retried stage must be idempotent.

    Theme rows are inserted, not upserted, so each re-run used to append a whole second
    set: 16 themes became 32, then 48, then 80 — every round reported as a normal result
    and every one of them wrong.
    """
    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    async def _theme_count() -> int:
        async with session_scope() as session:
            return len(
                list(
                    (
                        await session.execute(
                            select(Theme).where(Theme.run_id == run_uuid)
                        )
                    ).scalars()
                )
            )

    first = await _theme_count()
    assert first >= 1

    from backend.agents.nodes.theme import ThemeNode

    state = await load_state(run_uuid)
    await ThemeNode().run(state, run_uuid)
    assert await _theme_count() == first, (
        "re-running theme duplicated its output instead of replacing it"
    )


async def test_a_second_execution_of_one_run_is_refused_not_raced(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Two executions of the same run must not walk the pipeline together.

    claim_stage() short-circuits a stage that is COMPLETE or SKIPPED, but a stage that is
    RUNNING is still claimable, so a second execution interleaves through the one in
    flight. Several endpoints schedule an execution (resume, approve-all, stage retry,
    stage skip); pressing two produced the gate's repeated "GATE_OPENED / PAUSED" and let
    theme's inserts stack up into duplicate theme sets.
    """
    import asyncio

    run_uuid = await create_run(str(sample_csv), None)
    first, second = await asyncio.gather(
        execute_run(run_uuid), execute_run(run_uuid)
    )

    refused = [r for r in (first, second) if r.get("already_running")]
    assert len(refused) == 1, (
        "one of the two concurrent executions should have been refused, "
        f"got {[r.get('already_running') for r in (first, second)]}"
    )

    # And the work happened exactly once.
    gate_openings = [
        d for d in await _decisions(run_uuid) if d["decision"] == "GATE_OPENED"
    ]
    assert len(gate_openings) == 1, (
        f"the gate opened {len(gate_openings)} times for one run"
    )

    async with session_scope() as session:
        themes = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid)))
            .scalars()
        )
    names = [t.name for t in themes]
    assert len(names) == len(set(names)), f"duplicate themes created: {names}"


def test_a_document_whose_bodies_are_still_placeholders_is_detectable():
    """An export can be structurally perfect and contain nothing.

    The digest template ships with a heading per section and the body text
    "To be completed." A structural check — does the document have the expected headings?
    — passes on that blank template unchanged, so it confirms the template rather than
    the digest. This is the same mistake as the rest of this file in a different place:
    a check that cannot fail is not a check.

    Observed live: a run reported COMPLETE with 14 provider operations, 13 sections
    "applied" and a VERIFIED decision naming 10 confirmed sections, while the exported
    file still had six "To be completed." bodies. The content had been applied to a
    session that was then abandoned, and the replacement session started from a fresh
    template (backend/agents/nodes/superdocs.py:311-312 re-uploads TEMPLATE_HTML but
    resumes from the CURRENT section, so every section already applied is dropped).
    """
    placeholder = "To be completed."

    hollow = [
        "Voice-of-Customer Digest",
        "Executive Summary", placeholder,
        "Top Themes This Quarter", placeholder,
        "Methodology", placeholder,
    ]
    populated = [
        "Voice-of-Customer Digest",
        "Executive Summary", "Support volume concentrated in seven themes.",
        "Top Themes This Quarter", "| Theme | Volume |",
        "Methodology", "Themes were derived by clustering 8 conversations.",
    ]

    def unfilled_sections(paragraphs: list[str]) -> int:
        return sum(1 for p in paragraphs if p.strip() == placeholder)

    assert unfilled_sections(hollow) == 3, (
        "a document that is still the template must be detectable as such"
    )
    assert unfilled_sections(populated) == 0

    # The point of the test: a heading check cannot tell these two apart.
    headings_hollow = [p for p in hollow if p in {
        "Executive Summary", "Top Themes This Quarter", "Methodology"}]
    headings_populated = [p for p in populated if p in {
        "Executive Summary", "Top Themes This Quarter", "Methodology"}]
    assert headings_hollow == headings_populated, (
        "if this ever differs, a heading check would have caught the hollow document "
        "and this test is no longer describing the real gap"
    )
