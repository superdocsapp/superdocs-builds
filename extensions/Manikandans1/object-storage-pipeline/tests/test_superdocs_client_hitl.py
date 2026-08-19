"""Proves SuperDocsClient.edit_document() exercises the real, documented
HITL sequence when approval_mode="ask_every_time":

    POST /v1/chat/async
    GET  /v1/jobs/{job_id}            (poll — status: awaiting_approval)
    POST /v1/chat/{session_id}/approve
    GET  /v1/jobs/{job_id}            (poll — status: completed)

This is the sequence the task brief calls "the minimum contract with
us... upload a document, send an edit instruction, approve the proposed
changes, and export the finished file" — with approval done by the
pipeline itself rather than a human, since neither assigned card calls
for a human reviewer. It also proves the sync approve_all path
(POST /v1/chat only) still works as the faster alternative, and that a
continue_prompt pause (a large edit asking whether to keep going) is
handled distinctly from a change-review pause, per
docs.superdocs.app/guides/async-jobs#continuing-a-large-edit.

Entirely offline: httpx.MockTransport, no real network, no API key.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.superdocs_client import SuperDocsClient, SuperDocsError


def _json_response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


class ScriptedJobServer:
    """A tiny fake SuperDocs server that walks a job through a scripted
    sequence of statuses each time GET /v1/jobs/{job_id} is polled, and
    records every call it receives so tests can assert on the exact
    sequence and payload shape."""

    def __init__(self, job_id: str = "job_abc"):
        self.job_id = job_id
        self.calls: list[tuple[str, str, dict | None]] = []
        self._poll_count = 0
        self.approved_change_ids: list[str] | None = None
        self.continue_calls: list[bool] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path
        body = json.loads(request.content) if request.content else None
        self.calls.append((method, path, body))

        if method == "POST" and path == "/v1/chat/async":
            assert body["approval_mode"] == "ask_every_time"
            assert body["session_id"]
            assert body["message"]
            return _json_response(
                200,
                {"job_id": self.job_id, "session_id": body["session_id"], "status": "pending"},
            )

        if method == "GET" and path == f"/v1/jobs/{self.job_id}":
            return self._poll_response()

        if method == "POST" and path.endswith("/approve"):
            assert body["job_id"] == self.job_id
            assert body["approved"] is True  # required top-level field, per docs
            self.approved_change_ids = [c["change_id"] for c in body["changes"]]
            return _json_response(200, {"status": "ok"})

        if method == "POST" and path.endswith("/continue"):
            assert body["job_id"] == self.job_id
            self.continue_calls.append(body["continue"])
            return _json_response(200, {"status": "ok"})

        raise AssertionError(f"unexpected request: {method} {path}")

    def _poll_response(self) -> httpx.Response:
        raise NotImplementedError


class ChangeReviewThenCompleteServer(ScriptedJobServer):
    """poll 1: awaiting_approval with pending_changes
    poll 2 (after approve): completed"""

    def _poll_response(self) -> httpx.Response:
        self._poll_count += 1
        if self._poll_count == 1:
            return _json_response(
                200,
                {
                    "job_id": self.job_id,
                    "status": "awaiting_approval",
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "ch_1",
                                "operation": "edit",
                                "chunk_id": "abc",
                                "old_html": "<p>old</p>",
                                "new_html": "<p>new</p>",
                                "ai_explanation": "Reformatted heading",
                            }
                        ]
                    },
                },
            )
        return _json_response(
            200,
            {
                "job_id": self.job_id,
                "status": "completed",
                "result": {
                    "response": "Done.",
                    "session_id": "sess-1",
                    "document_changes": {
                        "updated_html": "<div>final</div>",
                        "changes_summary": "1 section edited",
                        "version_id": "v9",
                    },
                    "usage": {
                        "monthly_used": 5,
                        "monthly_limit": 500,
                        "monthly_remaining": 495,
                        "was_billable": True,
                    },
                },
            },
        )


class ContinuePromptThenCompleteServer(ScriptedJobServer):
    """poll 1: awaiting_approval with awaiting_kind=continue_prompt
    poll 2 (after continue): completed, with no separate approve call"""

    def _poll_response(self) -> httpx.Response:
        self._poll_count += 1
        if self._poll_count == 1:
            return _json_response(
                200,
                {
                    "job_id": self.job_id,
                    "status": "awaiting_approval",
                    "metadata": {
                        "awaiting_kind": "continue_prompt",
                        "continue_prompt": {
                            "message": "I've updated 500 of 864 sections. Continue?",
                            "done": 500,
                            "total": 864,
                            "remaining": 364,
                        },
                    },
                },
            )
        return _json_response(
            200,
            {
                "job_id": self.job_id,
                "status": "completed",
                "result": {
                    "response": "Finished.",
                    "session_id": "sess-1",
                    "document_changes": {"updated_html": "<div>final</div>"},
                    "usage": {"monthly_used": 6, "monthly_remaining": 494},
                },
            },
        )


class FailedJobServer(ScriptedJobServer):
    def _poll_response(self) -> httpx.Response:
        return _json_response(200, {"job_id": self.job_id, "status": "failed", "error": "boom"})


def _client_for(server: ScriptedJobServer, **overrides) -> SuperDocsClient:
    http = httpx.Client(transport=httpx.MockTransport(server.handler))
    return SuperDocsClient(
        base_url="https://fake-superdocs",
        api_key="unused",
        http_client=http,
        raw_http_client=httpx.Client(),
        poll_interval_seconds=0,  # don't slow the test suite down
        max_wait_seconds=5,
        **overrides,
    )


def test_ask_every_time_polls_reviews_and_auto_approves_then_returns_result():
    server = ChangeReviewThenCompleteServer()
    client = _client_for(server)

    result = client.edit_document("sess-1", "reformat this", approval_mode="ask_every_time")

    assert result.updated_html == "<div>final</div>"
    assert result.changes_summary == "1 section edited"
    assert result.monthly_remaining == 495

    # Exact documented sequence: start, poll (awaiting_approval), approve, poll (completed).
    kinds = [(m, p) for m, p, _ in server.calls]
    assert kinds == [
        ("POST", "/v1/chat/async"),
        ("GET", "/v1/jobs/job_abc"),
        ("POST", "/v1/chat/sess-1/approve"),
        ("GET", "/v1/jobs/job_abc"),
    ]
    assert server.approved_change_ids == ["ch_1"]


def test_continue_prompt_pause_is_resumed_not_treated_as_a_change_review():
    server = ContinuePromptThenCompleteServer()
    client = _client_for(server)

    result = client.edit_document("sess-1", "reformat this", approval_mode="ask_every_time")

    assert result.updated_html == "<div>final</div>"
    assert server.continue_calls == [True]
    assert server.approved_change_ids is None  # /approve was never called for this pause kind

    kinds = [(m, p) for m, p, _ in server.calls]
    assert kinds == [
        ("POST", "/v1/chat/async"),
        ("GET", "/v1/jobs/job_abc"),
        ("POST", "/v1/chat/sess-1/continue"),
        ("GET", "/v1/jobs/job_abc"),
    ]


def test_failed_job_raises_a_clear_error_not_a_silent_success():
    server = FailedJobServer()
    client = _client_for(server)

    with pytest.raises(SuperDocsError, match="boom"):
        client.edit_document("sess-1", "reformat this", approval_mode="ask_every_time")


def test_approve_all_mode_is_a_single_synchronous_call():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/chat"
        body = json.loads(request.content)
        assert body["approval_mode"] == "approve_all"
        return _json_response(
            200,
            {
                "response": "Done.",
                "session_id": body["session_id"],
                "document_changes": {"updated_html": "<div>ok</div>", "changes_summary": "updated"},
                "usage": {"monthly_used": 1, "monthly_remaining": 499},
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = SuperDocsClient(
        base_url="https://fake-superdocs", api_key="unused", http_client=http,
        raw_http_client=httpx.Client(),
    )

    result = client.edit_document("sess-1", "reformat this", approval_mode="approve_all")

    assert result.updated_html == "<div>ok</div>"
    assert result.monthly_remaining == 499
