"""
@file: backend/tests/test_degraded_mode.py
@description: Tests every external-service failure mode: no Groq key, Groq outage, no
    SuperDocs key, SuperDocs out of quota, SuperDocs unreachable. The system must in each
    case still produce a usable digest, and must disclose in the document itself that it
    ran degraded rather than presenting weaker output as normal.
@flow: clear or break a credential -> run the full pipeline -> assert it completed,
    assert an export exists, and assert the methodology section names the degraded
    stages.
@dependencies: conftest fixtures, backend.services.heuristics, backend.services.local_render
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from backend.agents.graph import create_run, execute_run, load_state
from backend.config import settings
from backend.db.database import session_scope
from backend.models import ApprovalItem, ApprovalStatus, Run, RunStatus, Theme
from backend.services.groq_client import GroqUnavailable

pytestmark = pytest.mark.asyncio


async def _approve_all(run_uuid) -> None:
    async with session_scope() as session:
        items = list(
            (
                await session.execute(
                    select(ApprovalItem).where(ApprovalItem.run_id == run_uuid)
                )
            ).scalars()
        )
        for item in items:
            item.status = ApprovalStatus.APPROVED


# ---------------------------------------------------------------- Groq missing


async def test_no_groq_key_still_produces_a_digest(
    test_db, fake_superdocs, sample_csv, monkeypatch
):
    """With no Groq key the run must complete on heuristics, not die."""
    monkeypatch.setattr(settings, "groq_api_key", None)

    run_uuid = await create_run(str(sample_csv), None)
    result = await execute_run(run_uuid)
    assert result["paused"] is True, "should still reach the human gate"

    state = await load_state(run_uuid)
    assert state["conversations_ingested"] == 6
    assert state["theme_count"] >= 1, "clustering is embedding-based and must still work"
    assert "classify" in state["degraded_stages"]
    assert "extract" in state["degraded_stages"]
    assert state["degraded_caveats"], "degradation must carry an explanation"

    await _approve_all(run_uuid)
    final = await execute_run(run_uuid)
    assert final["status"] == RunStatus.COMPLETE.value

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        assert run.export_path and Path(run.export_path).is_file()


async def test_degraded_run_discloses_itself_in_the_document(
    test_db, fake_superdocs, sample_csv, monkeypatch
):
    """The digest must say it ran without a model. Silent degradation is the failure."""
    monkeypatch.setattr(settings, "groq_api_key", None)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    state = await load_state(run_uuid)

    methodology = state["draft_sections"]["methodology"]
    assert "WITHOUT a language model" in methodology
    assert "keyword heuristics" in methodology
    assert "materially reduces quality" in methodology
    for stage in state["degraded_stages"]:
        assert stage in methodology, f"{stage} not disclosed in methodology"


async def test_groq_outage_mid_run_degrades_rather_than_failing(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """An outage (not a missing key) must also fall back rather than fail the run."""
    fake_groq.fail_with = GroqUnavailable("service unavailable", retryable=True)

    run_uuid = await create_run(str(sample_csv), None)
    result = await execute_run(run_uuid)

    assert result["paused"] is True
    state = await load_state(run_uuid)
    assert state["degraded_stages"], "outage should have triggered degradation"
    assert state["theme_count"] >= 1


async def test_degraded_disabled_pauses_instead(
    test_db, fake_superdocs, sample_csv, monkeypatch
):
    """With ALLOW_DEGRADED_ANALYSIS=false a missing key pauses, and does not fail.

    Pausing preserves completed stages so the run can be resumed once the key is added;
    failing would discard them.
    """
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "allow_degraded_analysis", False)

    run_uuid = await create_run(str(sample_csv), None)
    result = await execute_run(run_uuid)

    assert result["status"] == RunStatus.PAUSED.value
    assert "GROQ_API_KEY" in (result.get("reason") or "")

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        stages = (run.checkpoint_data or {}).get("stages", {})
    # Ingest finished before the key was needed and must survive the pause.
    assert stages["ingest"]["status"] == "COMPLETE"
    # And it must not have burned retries on something a retry cannot fix.
    assert stages.get("classify", {}).get("attempts", 1) == 1


# ---------------------------------------------------------------- SuperDocs missing


async def test_no_superdocs_key_renders_locally(
    test_db, fake_groq, sample_csv, monkeypatch
):
    """Without SuperDocs the digest is still produced, locally."""
    monkeypatch.setattr(settings, "superdocs_api_key", None)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    result = await execute_run(run_uuid)

    assert result["status"] == RunStatus.COMPLETE.value
    state = await load_state(run_uuid)
    assert state["rendered_locally"] is True

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        path = Path(run.export_path)
    assert path.is_file() and path.stat().st_size > 0

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        decisions = [d["decision"] for d in (run.decision_log or [])]
    assert "RENDERED_LOCALLY" in decisions


async def test_superdocs_quota_exhausted_mid_run_falls_back(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """Running out of credits part-way must not strand approved content."""
    from backend.services.superdocs_client import SuperDocsQuotaError

    fake_superdocs.fail_edit_with = SuperDocsQuotaError(
        "monthly operation quota exhausted", status_code=429
    )

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    result = await execute_run(run_uuid)

    assert result["status"] == RunStatus.COMPLETE.value
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        assert Path(run.export_path).is_file()
        reasons = [d["reason"] for d in (run.decision_log or [])
                   if d["decision"] == "RENDERED_LOCALLY"]
    assert reasons and "quota" in reasons[0].lower()


async def test_local_render_disabled_pauses_instead(
    test_db, fake_groq, sample_csv, monkeypatch
):
    monkeypatch.setattr(settings, "superdocs_api_key", None)
    monkeypatch.setattr(settings, "allow_local_render", False)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    result = await execute_run(run_uuid)

    assert result["status"] != RunStatus.COMPLETE.value
    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
    # Analysis is preserved so the run can resume once a key is supplied.
    assert run.checkpoint_data["stages"]["draft"]["status"] == "COMPLETE"


# ---------------------------------------------------------------- both missing


async def test_neither_service_available_still_produces_a_digest(
    test_db, sample_csv, monkeypatch
):
    """The worst case: no Groq, no SuperDocs. A digest must still come out."""
    monkeypatch.setattr(settings, "groq_api_key", None)
    monkeypatch.setattr(settings, "superdocs_api_key", None)

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)
    await _approve_all(run_uuid)
    result = await execute_run(run_uuid)

    assert result["status"] == RunStatus.COMPLETE.value

    async with session_scope() as session:
        run = await session.get(Run, run_uuid)
        themes = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid))).scalars()
        )
        path = Path(run.export_path)

    assert path.is_file() and path.stat().st_size > 0
    assert themes, "themes must still be produced"
    assert all(t.evidence_refs for t in themes), "citations must survive degradation"

    state = await load_state(run_uuid)
    assert state["rendered_locally"] is True
    assert state["degraded_stages"]
    # And the reader is told, in the document.
    assert "WITHOUT a language model" in state["draft_sections"]["methodology"]


async def test_anonymization_still_runs_without_groq(
    test_db, sample_csv, monkeypatch
):
    """Regex redaction must survive an LLM outage.

    Emails and phone numbers are the highest-confidence redactions and do not need a
    model; losing them silently would be a privacy failure, not a quality one.
    """
    monkeypatch.setattr(settings, "groq_api_key", None)

    csv_path = sample_csv.parent / "pii.csv"
    csv_path.write_text(
        "text,date\n"
        '"Hi I am Sarah Chen, email sarah.chen@northwind.com, phone 555-234-5678, '
        'and my export keeps failing every single time I try it.",2026-07-01\n',
        encoding="utf-8",
    )

    run_uuid = await create_run(str(csv_path), None)
    await execute_run(run_uuid)

    async with session_scope() as session:
        themes = list(
            (await session.execute(select(Theme).where(Theme.run_id == run_uuid))).scalars()
        )
    quotes = [q for t in themes for q in (t.representative_quotes or [])]
    assert quotes, "quotes should still be selected"
    blob = " ".join(q["anonymized"] for q in quotes)
    assert "sarah.chen@northwind.com" not in blob, "email leaked without Groq"
    assert "555-234-5678" not in blob, "phone leaked without Groq"
    assert "[EMAIL]" in blob and "[PHONE]" in blob


# ------------------------------------------------- provider-specific requirements


def test_json_mode_always_includes_the_word_json():
    """Groq rejects json_object mode unless "json" appears in the messages.

    Found on first contact with the live API: every classify call returned
    400 "'messages' must contain the word 'json' in some form". OpenAI imposes no such
    requirement, so prompts that work there fail on Groq. The guard lives at the single
    point where the mode is enabled rather than depending on prompt authors remembering.
    """
    import json as json_mod

    import httpx

    from backend.services.groq_client import GroqClient

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json_mod.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"ok": true}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = GroqClient(api_key="test", client=http)
            # A system prompt that deliberately avoids the word "json".
            await client.complete_json(
                "You classify records. Return ONLY a structured object.",
                "Classify these records.",
                untrusted_content="[0] the export button does nothing at all",
            )

    import asyncio

    asyncio.run(run())

    assert captured.get("response_format") == {"type": "json_object"}
    blob = " ".join(str(m["content"]).lower() for m in captured["messages"])
    assert "json" in blob, (
        "json_object mode was requested without the word 'json' in any message — "
        "Groq returns 400 for this"
    )


def test_json_mode_does_not_duplicate_the_hint():
    """A prompt that already says "json" must not get the instruction appended twice."""
    import json as json_mod

    import httpx

    from backend.services.groq_client import GroqClient

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json_mod.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            client = GroqClient(api_key="test", client=http)
            await client.complete_json(
                "Return ONLY a JSON object with this shape: {\"a\": 1}",
                "Go.",
            )

    import asyncio

    asyncio.run(run())

    system = captured["messages"][0]["content"]
    assert system.count("Respond with a single valid JSON object") == 0, (
        "hint appended even though the prompt already mentioned JSON"
    )


# ---------------------------------------------------- anonymizer batching


def test_name_prescreen_skips_quotes_without_names():
    """Quotes with no name-shaped token must not trigger an LLM call.

    This is the fix for the anonymizer's original shape, which made one sequential
    request per quote — ~144 calls on a 200-conversation run, minutes of wall clock, and
    most of the token spend, for quotes that mostly contain no names at all.
    """
    from backend.services.anonymizer import has_name_candidate

    assert not has_name_candidate(
        "The export button does nothing and no file downloads."
    )
    assert not has_name_candidate("Dashboard is slow every morning.")
    # Product and platform words are capitalised but are never personal names.
    assert not has_name_candidate("The Export feature and Dashboard are both broken.")

    assert has_name_candidate("Hi, I'm Sarah Chen and my export fails.")
    assert has_name_candidate("This is Marcus at Vertex Media.")


@pytest.mark.asyncio
async def test_batched_anonymize_makes_one_call_for_many_quotes(fake_groq):
    """A group of quotes must cost one LLM call, not one per quote."""
    from backend.services.anonymizer import Anonymizer

    fake_groq.calls = []
    anonymizer = Anonymizer(fake_groq())

    quotes = [
        "Hi, I'm Sarah Chen and the export keeps failing on me every time.",
        "The dashboard is extremely slow to load every single morning.",
        "Export produces an empty file with only headers in it.",
    ]
    results = await anonymizer.anonymize_many(quotes)

    assert len(results) == 3
    assert len(fake_groq.calls) == 1, (
        f"expected one batched call, got {len(fake_groq.calls)}"
    )


@pytest.mark.asyncio
async def test_batching_does_not_weaken_redaction(fake_groq):
    """The batched path must redact exactly as thoroughly as the per-quote path did.

    Speed is not worth a leak, so this asserts on the output rather than the call count.
    """
    from backend.services.anonymizer import Anonymizer

    anonymizer = Anonymizer(fake_groq())
    quotes = [
        "Hi, I'm Sarah Chen, reach me at sarah.chen@northwind.com or 555-234-5678.",
        "Ticket TKT-449182 for account ACCT-93737 is still unresolved.",
    ]
    results = await anonymizer.anonymize_many(quotes)
    blob = " ".join(r.anonymized for r in results)

    assert "sarah.chen@northwind.com" not in blob
    assert "555-234-5678" not in blob
    assert "Sarah Chen" not in blob
    assert "[EMAIL]" in blob and "[PHONE]" in blob and "[USER]" in blob
    assert "TKT-449182" not in blob and "ACCT-93737" not in blob


@pytest.mark.asyncio
async def test_model_silence_is_not_treated_as_clean(fake_groq):
    """If the model returns no analysis for a quote, that must be flagged.

    Treating silence as "no names found" would hand out an unearned clean bill of health.
    """
    from backend.services.anonymizer import Anonymizer

    class SilentGroq(fake_groq):
        async def complete_json(self, *a, **kw):
            from backend.services.groq_client import LLMUsage

            return {"results": []}, LLMUsage(calls=1), False

    anonymizer = Anonymizer(SilentGroq())
    results = await anonymizer.anonymize_many(
        ["Hi, I'm Sarah Chen and my export is broken again today."]
    )
    assert results[0].needs_review is True
    assert any("no name analysis" in s for s in results[0].uncertain_spans)


# ------------------------------------------------- rate limits and the circuit breaker

REAL_GROQ_429 = (
    'Rate limit reached for model `llama-3.3-70b-versatile` in organization `org_x` '
    "service tier `on_demand` on tokens per day (TPD): Limit 100000, Used 99792, "
    "Requested 612. Please try again in 5m49.056s."
)


@pytest.mark.filterwarnings("ignore::pytest.PytestWarning")
def test_parses_groq_retry_hint_and_limit_window():
    """Groq states the wait in the error text, not only in a header."""
    from backend.services.groq_client import is_daily_quota, parse_retry_after

    assert parse_retry_after(REAL_GROQ_429) == pytest.approx(349.056, abs=0.01)
    assert is_daily_quota(REAL_GROQ_429) is True

    burst = "on tokens per minute (TPM): ... Please try again in 4.2s."
    assert parse_retry_after(burst) == pytest.approx(4.2)
    assert is_daily_quota(burst) is False


@pytest.mark.asyncio
async def test_daily_quota_fails_fast_instead_of_retrying():
    """A spent daily allowance must not be retried.

    Observed in production: the client capped Groq's stated 20-minute wait at 60s and
    retried three times, per batch, across 25 themes — turning a 40-conversation run into
    three hours of 429s. A per-day limit must raise immediately.
    """
    import httpx

    from backend.services.groq_client import GroqClient, GroqQuotaExhausted

    attempts = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(429, json={"error": {"message": REAL_GROQ_429}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GroqClient(api_key="test", client=http)
        with pytest.raises(GroqQuotaExhausted) as exc:
            await client.complete("sys", "user")

    assert attempts["n"] == 1, f"should not retry a daily limit, made {attempts['n']} calls"
    assert exc.value.retryable is False
    assert exc.value.retry_after_s == pytest.approx(349.056, abs=0.01)


@pytest.mark.asyncio
async def test_short_burst_limit_is_still_retried():
    """A per-minute limit clears quickly and should be waited out, not given up on."""
    import httpx

    from backend.services.groq_client import GroqClient

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"error": {"message": "on tokens per minute (TPM). "
                                           "Please try again in 0.01s."}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ok"}}],
                  "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = GroqClient(api_key="test", client=http)
        result = await client.complete("sys", "user")

    assert calls["n"] == 2, "a short burst limit should be retried once"
    assert result.content == "ok"


@pytest.mark.asyncio
async def test_breaker_stops_further_calls_after_quota_exhaustion():
    """One exhaustion must be enough — later stages skip the call entirely."""
    import httpx

    from backend.services.groq_client import GroqClient
    from backend.services.heuristics import heuristic_classify
    from backend.services.llm_gate import (
        breaker_is_open,
        reset_breaker,
        run_with_fallback,
    )

    reset_breaker()
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, json={"error": {"message": REAL_GROQ_429}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        async def llm():
            client = GroqClient(api_key="test", client=http)
            payload, usage, _ = await client.complete_json("sys", "user")
            return payload, usage

        first = await run_with_fallback(
            "classify", llm, lambda: heuristic_classify(["export is broken"])
        )
        assert first.degraded is True
        assert breaker_is_open() is True
        assert calls["n"] == 1

        # Four more stages. None should reach the network.
        for stage in ("extract", "theme", "compare", "draft"):
            result = await run_with_fallback(
                stage, llm, lambda: heuristic_classify(["export is broken"])
            )
            assert result.degraded is True

    assert calls["n"] == 1, (
        f"breaker should have prevented further calls, but {calls['n']} were made"
    )
    reset_breaker()


@pytest.mark.asyncio
async def test_breaker_resets_between_runs(
    test_db, fake_groq, fake_superdocs, sample_csv
):
    """A quota spent an hour ago may have reset — a new run deserves a real attempt."""
    from backend.services.llm_gate import breaker_is_open, trip_breaker

    trip_breaker("previous run exhausted the allowance", 3600)
    assert breaker_is_open() is True

    run_uuid = await create_run(str(sample_csv), None)
    await execute_run(run_uuid)

    assert breaker_is_open() is False, "execute_run must reset the breaker"
    assert fake_groq.calls, "the new run should have attempted real calls"


# ------------------------------------------------- SuperDocs session recovery

SESSION_BUSY_BODY = {
    "error_code": "session_busy",
    "message": "The AI is still working on a previous request in this conversation.",
    "suggested_action": "Poll get_job/list_jobs for the active job, cancel it with "
                        "cancel_job, or use a different session_id.",
    "active_jobs": 1,
}


@pytest.mark.asyncio
async def test_session_busy_is_classified_separately_from_other_conflicts():
    """A 409 session_busy is recoverable; a wrong-endpoint 409 is not.

    Observed against the live API: a run that failed mid-edit left an active job in its
    session. Because session ids are deterministic so that retries reconnect, the retry
    hit its own orphaned job and was rejected — permanently, since both 409s were treated
    as the same unrecoverable error.
    """
    import httpx

    from backend.services.superdocs_client import (
        SuperDocsClient,
        SuperDocsError,
        SuperDocsSessionBusy,
    )

    # _classify_error is pure — it inspects a response and returns an exception — so the
    # client needs no live transport. Building one and leaving it unclosed leaked a
    # connection pool into the rest of the suite.
    async with httpx.AsyncClient() as http:
        client = SuperDocsClient(api_key="test", client=http)

    busy = client._classify_error(
        httpx.Response(409, json=SESSION_BUSY_BODY), "POST", "/v1/chat/async"
    )
    assert isinstance(busy, SuperDocsSessionBusy)
    assert busy.active_jobs == 1
    # The message must point at the real cause, not blame awaiting_kind.
    assert "active job" in str(busy)
    assert "awaiting_kind" not in str(busy)

    other = client._classify_error(
        httpx.Response(409, json={"detail": "wrong endpoint for this pause"}),
        "POST",
        "/v1/chat/session/approve",
    )
    assert isinstance(other, SuperDocsError)
    assert not isinstance(other, SuperDocsSessionBusy)
    assert "awaiting_kind" in str(other)


@pytest.mark.asyncio
async def test_clear_active_jobs_cancels_only_unfinished_ones():
    """Stale jobs are cancelled; completed ones are left alone."""
    import httpx

    from backend.services.superdocs_client import SuperDocsClient

    cancelled: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/jobs":
            return httpx.Response(200, json={"jobs": [
                {"job_id": "job-done", "status": "completed"},
                {"job_id": "job-stuck", "status": "in_progress"},
                {"job_id": "job-waiting", "status": "awaiting_approval"},
                {"job_id": "job-failed", "status": "failed"},
            ]})
        if request.url.path.endswith("/cancel"):
            cancelled.append(request.url.path.split("/")[-2])
            return httpx.Response(200, json={"cancelled": True})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsClient(api_key="test", client=http)
        count = await client.clear_active_jobs("vocdigest-abc")

    assert count == 2
    assert set(cancelled) == {"job-stuck", "job-waiting"}
    assert "job-done" not in cancelled and "job-failed" not in cancelled


@pytest.mark.asyncio
async def test_clear_active_jobs_survives_an_unlistable_session():
    """If jobs cannot be listed, clearing reports zero rather than failing the run."""
    import httpx

    from backend.services.superdocs_client import SuperDocsClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsClient(api_key="test", client=http)
        assert await client.clear_active_jobs("vocdigest-abc") == 0


def test_session_busy_detected_when_error_code_is_nested():
    """The 409 body nests error_code under "detail".

    Checking only the top level meant the session_busy handling existed but never ran —
    the error surfaced as a generic wrong-endpoint conflict, which sent debugging in
    entirely the wrong direction.
    """
    import asyncio

    import httpx

    from backend.services.superdocs_client import SuperDocsClient, SuperDocsSessionBusy

    nested = {
        "detail": {
            "error_code": "session_busy",
            "message": "The AI is still working on a previous request.",
            "active_jobs": 1,
        }
    }

    async def run():
        async with httpx.AsyncClient() as http:
            client = SuperDocsClient(api_key="test", client=http)
            return client._classify_error(
                httpx.Response(409, json=nested), "POST", "/v1/chat/async"
            )

    error = asyncio.run(run())
    assert isinstance(error, SuperDocsSessionBusy), (
        f"nested error_code was not detected; got {type(error).__name__}"
    )
    assert error.active_jobs == 1


@pytest.mark.asyncio
async def test_wait_for_session_free_returns_once_jobs_settle():
    """The wait must end when the session clears, not on a fixed sleep."""
    import httpx

    from backend.services.superdocs_client import SuperDocsClient

    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        # Busy for the first two polls, then free.
        status = "in_progress" if calls["n"] <= 2 else "completed"
        return httpx.Response(200, json={"jobs": [{"job_id": "j1", "status": status}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsClient(api_key="test", client=http)
        assert await client.wait_for_session_free("s1", timeout_s=30) is True

    assert calls["n"] == 3, f"should have polled until free, polled {calls['n']}x"


@pytest.mark.asyncio
async def test_wait_for_session_free_times_out_rather_than_hanging():
    import httpx

    from backend.services.superdocs_client import SuperDocsClient

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"jobs": [{"job_id": "j1", "status": "in_progress"}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = SuperDocsClient(api_key="test", client=http)
        assert await client.wait_for_session_free("s1", timeout_s=0.3) is False