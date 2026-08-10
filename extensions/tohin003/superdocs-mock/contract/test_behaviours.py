"""L3 -- the behaviour ledger, asserted.

Every test here names the `B-ID` it covers in a `covers` marker, and
`scripts/check_ledger_coverage.py` fails CI if a ledger row has no test or a test cites a
row that does not exist. That is what stops the ledger becoming documentation nobody runs.

These are the invariants an integration is actually built on -- the double-parse, the two
flavours of pause, the two kinds of 429, the shape of a refusal. They run against the mock
for free and against live to prove the mock still tells the truth.
"""

from __future__ import annotations

import json

import pytest


def covers(*ids: str):
    """Tag a test with the ledger rows it asserts."""
    return pytest.mark.covers(*ids)


# ------------------------------------------------------------------ authentication


@pytest.mark.rest
@covers("B-002")
def test_missing_authorization_returns_the_documented_401(api):
    response = api.client.post("/v1/chat", json={"message": "x", "session_id": "s"})
    assert response.status_code == 401
    assert "Bearer" in response.json()["detail"]


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-005", "B-093")
def test_usage_endpoint_rejects_api_keys(api):
    """Web-app-only, and it says so clearly rather than 403-ing or 404-ing."""
    api.using("account-status")
    api.get("/v1/agents/whoami")
    api.get("/v1/users/me/promotions")
    response = api.get("/v1/users/me/usage")
    assert response.status_code == 401
    assert "session" in response.json()["detail"].lower()


# ------------------------------------------------------------------ the review loop


@pytest.mark.rest
@pytest.mark.billable
@covers("B-023", "B-024", "B-025", "B-026", "B-040", "B-044", "B-045")
def test_a_review_turn_pauses_with_proposals(journey):
    """Review mode pauses the job and hands back structured proposals."""
    job_id = journey.start_review()
    body = journey.await_review(job_id)

    assert body["status"] == "awaiting_approval", body.get("status")
    pending = (body.get("metadata") or {}).get("pending_changes") or []
    assert pending, "a review pause with no pending changes is not reviewable"

    for change in pending:
        assert change["change_id"]
        assert change["operation"] in {"edit", "create", "delete"}
        if change["operation"] == "edit":
            assert change.get("old_html") and change.get("new_html")
        if change["operation"] == "create":
            assert change.get("new_html") and change.get("old_html") is None
        if change["operation"] == "delete":
            assert change.get("old_html") and change.get("new_html") is None


@pytest.mark.rest
@pytest.mark.billable
@covers("B-041", "B-042")
def test_approve_requires_top_level_approved_even_in_batch(journey, api):
    """The single most-warned-about trap in the approval docs, asserted.

    A batch body carrying `changes` but no top-level `approved` is rejected 422. It is
    the shape integrators reach for first, and it is the one that does not work.
    """
    job_id = journey.start_review()
    body = journey.await_review(job_id)
    pending = (body.get("metadata") or {}).get("pending_changes") or []
    if not pending:
        pytest.skip("no proposals to decide on")

    response = api.post(
        f"/v1/chat/{journey.session_id}/approve",
        json={"job_id": job_id, "changes": [{"change_id": pending[0]["change_id"]}]},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any(entry.get("loc", [])[-1] == "approved" for entry in detail), detail


@pytest.mark.rest
@covers("B-033", "B-034", "B-035", "B-036")
def test_a_continue_pause_is_told_apart_from_a_review_pause(api, target):
    """The two flavours of awaiting_approval, and the 409 that guards the boundary.

    Served from a synthesised cassette, because the pause could not be induced live
    inside the recording budget (a real 400-section edit finished in one turn). Skipped
    against live rather than faked there.
    """
    if target == "live":
        pytest.skip(
            "a continue_prompt pause cannot be induced on demand; see the "
            "paused-large-edit synthesis note"
        )
    api.using("paused-large-edit")
    job = api.get("/v1/jobs/550e8400-e29b-41d4-a716-446655440000").json()
    meta = job["metadata"]

    assert job["status"] == "awaiting_approval"
    assert meta["awaiting_kind"] == "continue_prompt"
    assert not meta.get("pending_changes"), (
        "a continue pause must carry no pending_changes -- that is how it is told apart"
    )
    prompt = meta["continue_prompt"]
    assert prompt["done"] + prompt["remaining"] == prompt["total"]

    wrong = api.post("/v1/chat/sdmock-continue-001/approve",
                     json={"job_id": "550e8400-e29b-41d4-a716-446655440000",
                           "approved": True})
    assert wrong.status_code == 409, "approve on a continue pause must be refused"

    right = api.post("/v1/chat/sdmock-continue-001/continue",
                     json={"job_id": "550e8400-e29b-41d4-a716-446655440000",
                           "continue": True})
    assert right.status_code == 200


# ------------------------------------------------------------------ streaming


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-051", "B-052", "B-053", "B-054")
def test_proposed_change_batch_content_needs_a_second_parse(api):
    """B-052, the trap the integration docs warn about twice.

    `content` arrives as a JSON-encoded *string*; `final.result` is already an object.
    Missing the asymmetry is the documented reason integrators see diff cards where
    every field reads undefined -- so the mock must reproduce it exactly, and this is
    the test that says it does.
    """
    api.using("proposed-change-batch")
    response = api.get("/v1/chat/s/stream", params={"job_id": "j", "api_key": "k"})
    events = _sse(response.text)

    batches = [payload for name, payload in events if name == "proposed_change_batch"]
    assert batches, "no proposed_change_batch event in the stream"

    outer = batches[0]
    assert isinstance(outer["content"], str), (
        "content is already parsed -- the double-encoding is gone; check whether the "
        "service changed before relaxing this"
    )
    inner = json.loads(outer["content"])
    assert inner["type"] in {"batch_approval", "single_approval"}
    assert inner["batch_total"] == len(inner["changes"])
    assert inner["batch_id"] == inner["changes"][0]["change_id"]

    finals = [payload for name, payload in events if name == "final"]
    if finals:
        assert isinstance(finals[0]["result"], dict), (
            "final.result must already be an object -- that asymmetry is the point"
        )


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-055", "B-056", "B-057", "B-104")
def test_stream_resume_returns_only_newer_events(api):
    api.using("proposed-change-batch")

    def sequences(last: int | None) -> list[int]:
        params = {"job_id": "j", "api_key": "k"}
        if last is not None:
            params["last_sequence"] = str(last)
        return [p.get("sequence") for _, p in
                _sse(api.get("/v1/chat/s/stream", params=params).text)]

    full = sequences(None)
    assert full == sorted(full), "sequences are delivered out of order"
    for cutoff in (2, 5, 9):
        assert all(s > cutoff for s in sequences(cutoff))


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-058")
def test_document_sync_arrives_before_any_proposal(api):
    api.using("proposed-change-batch")
    names = [name for name, _ in
             _sse(api.get("/v1/chat/s/stream",
                          params={"job_id": "j", "api_key": "k"}).text)]
    assert names[0] == "document_sync", names[:3]
    assert names.index("document_sync") < names.index("proposed_change_batch")


# ------------------------------------------------------------------ refusals


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-064", "B-065", "B-067")
def test_quota_exhaustion_carries_retry_after_and_usage_headers(api):
    api.using("rate-limit")
    response = api.post("/v1/chat", json={"message": "x", "session_id": "s"})
    assert response.status_code == 429
    assert response.headers["retry-after"].isdigit()
    assert response.headers["x-usage-remaining"] == "0"
    assert response.headers["x-usage-limit"] == response.headers["x-usage-used"]
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-066")
def test_an_infrastructure_throttle_is_plain_text_with_no_retry_after(api):
    """The two 429s need different client handling, so they must stay tellable apart."""
    api.using("rate-limit-surge")
    response = api.post("/v1/chat", json={"message": "x", "session_id": "s"})
    assert response.status_code == 429
    assert response.headers.get("retry-after") is None
    assert not response.headers["content-type"].startswith("application/json")


@pytest.mark.rest
@covers("B-073", "B-074", "B-108")
def test_a_capacity_refusal_is_structured_and_expandable(api, target):
    """A refusal that tells an agent how to recover is worth more than a 500."""
    if target == "live":
        pytest.skip("re-uploading a 25,000-section document to observe a known 413 "
                    "puts real load on a live service for no new information")
    api.using("capacity-refusal")
    response = api.post("/v1/documents/upload")
    assert response.status_code == 413

    detail = response.json()["detail"]
    assert detail["error_code"] == "DOCUMENT_TOO_COMPLEX"
    assert detail["limit_expandable"] is True, (
        "the whole point of this refusal is that the limit is not a hard cap"
    )
    assert detail["section_count"] > detail["max_sections"]
    assert detail["contact_email"] == "hello@superdocs.app"
    assert detail["request_increase"]["mcp_tool"] == "request_limit_increase"


@pytest.mark.rest
@covers("B-069", "B-107")
def test_upload_format_handling_matches_what_the_service_actually_does(api, target):
    """F-003 and F-005, asserted against reality rather than against the docs.

    `.doc` is refused with a 400 (the docs promise 415) and `.odt` is accepted (the docs'
    supported-type list omits it). Both assertions fail if either behaviour is corrected,
    which is exactly when the findings should be revisited.
    """
    if target == "live":
        pytest.skip("covered by the recorded cassette; re-probing spends nothing but "
                    "adds nothing")
    api.using("unsupported-format")
    legacy = api.post("/v1/documents/upload")
    assert legacy.status_code == 400, (
        "the .doc refusal changed -- if it is now 415, F-005 is fixed"
    )
    accepted = api.post("/v1/documents/upload")
    assert accepted.status_code == 200, ".odt stopped being accepted; F-003 has moved"


# ------------------------------------------------------------------ billing


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-018", "B-020", "B-106", "B-109")
def test_usage_reports_the_bucket_and_the_count(api):
    """A large edit bills one operation per 25 sections, from a named bucket."""
    api.using("large-multi-section-edit")
    api.get("/v1/jobs/x")  # first poll: in progress
    body = api.get("/v1/jobs/x").json()
    usage = (body.get("result") or {}).get("usage") or {}
    assert usage.get("was_billable") is True
    assert usage["ops_charged"] >= 1
    assert usage["bucket_used"] in {"tier", "promo"}
    assert isinstance(usage.get("promotions"), list), (
        "the usage block carries the promo bucket that whoami omits -- see F-001"
    )


# ------------------------------------------------------------------ helpers


def _sse(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) pairs."""
    out: list[tuple[str, dict]] = []
    name = "message"
    for line in text.splitlines():
        if line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            out.append((name, json.loads(line[5:].strip())))
            name = "message"
    return out


@pytest.mark.rest
@covers("B-111")
def test_export_from_an_empty_session_is_an_actionable_404(journey):
    """Wiring up the four-call contract out of order is a common first mistake.

    The response says what is wrong and what to do about it, rather than returning an
    empty document -- which is the failure an integrator would ship without noticing.
    """
    response = journey.export_from_empty_session()
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert "No document loaded" in detail
    assert "Load a document first" in detail


@pytest.mark.rest
@pytest.mark.mock_only
@covers("B-016")
def test_compact_mode_suppresses_the_full_document(api):
    """B-016, asserted on a response rather than on the spec's prose.

    Compact mode exists so an agent editing a large document does not pay for the whole
    thing on every turn. Returning `updated_html` anyway is a silent cost regression --
    nothing errors, the context bill just doubles. The kill matrix found this gap: a
    mutant that ignored compact mode survived the whole suite.
    """
    api.using("large-multi-section-edit")
    api.get("/v1/jobs/x")  # in progress
    body = api.get("/v1/jobs/x").json()
    changes = (body.get("result") or {}).get("document_changes") or {}

    assert changes.get("updated_html") is None, (
        "compact mode returned the full document; the whole point of it is that it "
        "does not"
    )
    diffs = changes.get("chunk_diffs") or []
    assert diffs, "compact mode must return per-section diffs in place of the document"
    for diff in diffs[:5]:
        assert diff["change_id"] and diff["operation"]
