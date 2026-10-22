"""SuperDocsClient tests. No API key, no network, no operations spent.

The transport is injected, so every branch that would otherwise need a live
account -- 404 fallback, budget refusal, job failure, cold-start timeout -- is
exercised deterministically here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from superdocs_client import (  # noqa: E402
    BudgetExceeded,
    JobFailed,
    JobTimeout,
    OpsLedger,
    SuperDocsClient,
    SuperDocsError,
    Usage,
    load_dotenv,
)


class FakeResponse:
    def __init__(self, status_code: int = 200, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeTransport:
    """Scripted transport. Records every call for assertions."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url))
        return self.handler(method, url, kwargs, len(self.calls) - 1)


def make_client(handler, **kwargs) -> tuple[SuperDocsClient, FakeTransport, list[str]]:
    transport = FakeTransport(handler)
    printed: list[str] = []
    client = SuperDocsClient(
        api_key="sk_test_key",
        transport=transport,
        sleep=lambda _s: None,
        printer=printed.append,
        **kwargs,
    )
    return client, transport, printed


def job_payload(status="awaiting_approval", *, usage=None, pending=None, **extra):
    payload = {
        "job_id": "job_1",
        "session_id": "s1",
        "status": status,
        "result": {"usage": usage} if usage else {},
        "metadata": {"pending_changes": pending or []},
    }
    payload.update(extra)
    return payload


# -- construction / auth --------------------------------------------------


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    with pytest.raises(SuperDocsError, match="No API key"):
        SuperDocsClient()


def test_verify_key_distinguishes_rejected_from_broken():
    client, _, _ = make_client(lambda *a: FakeResponse(200, {"sessions": []}))
    assert client.verify_key() is True

    client, _, _ = make_client(lambda *a: FakeResponse(401, text="unauthorized"))
    assert client.verify_key() is False

    client, _, _ = make_client(lambda *a: FakeResponse(500, text="boom"))
    with pytest.raises(SuperDocsError):
        client.verify_key()


def test_auth_header_is_bearer():
    seen = {}

    def handler(method, url, kwargs, n):
        seen.update(kwargs.get("headers") or {})
        return FakeResponse(200, {"sessions": []})

    client, _, _ = make_client(handler)
    client.verify_key()
    assert seen["Authorization"] == "Bearer sk_test_key"


# -- chat_async -----------------------------------------------------------


def test_chat_async_returns_job_id():
    def handler(method, url, kwargs, n):
        assert kwargs["json"]["approval_mode"] == "ask_every_time"
        assert kwargs["json"]["async_mode"] is True
        return FakeResponse(200, {"job_id": "job_42"})

    client, transport, _ = make_client(handler)
    assert client.chat_async(message="hi", session_id="s1") == "job_42"
    assert transport.calls[0][1].endswith("/v1/chat/async")


def test_chat_async_falls_back_to_alternate_path_on_404():
    """The docs disagree with themselves on this path (PROGRESS.md A2)."""

    def handler(method, url, kwargs, n):
        if url.endswith("/v1/chat/async"):
            return FakeResponse(404, text="not found")
        return FakeResponse(200, {"job_id": "job_fallback"})

    client, transport, _ = make_client(handler)
    assert client.chat_async(message="hi", session_id="s1") == "job_fallback"
    assert len(transport.calls) == 2
    assert transport.calls[1][1].endswith("/v1/chat-async")


def test_chat_async_raises_when_every_path_404s():
    client, _, _ = make_client(lambda *a: FakeResponse(404, text="nope"))
    with pytest.raises(SuperDocsError, match="no async endpoint responded"):
        client.chat_async(message="hi", session_id="s1")


def test_chat_async_raises_on_missing_job_id():
    client, _, _ = make_client(lambda *a: FakeResponse(200, {"session_id": "s1"}))
    with pytest.raises(SuperDocsError, match="no job_id"):
        client.chat_async(message="hi", session_id="s1")


def test_non_json_response_is_reported_readably():
    client, _, _ = make_client(lambda *a: FakeResponse(200, None, text="<html>502</html>"))
    with pytest.raises(SuperDocsError, match="not JSON"):
        client.chat_async(message="hi", session_id="s1")


# -- budget ---------------------------------------------------------------


def test_budget_is_enforced_before_dispatch():
    """A cap checked after the call is not a cap (PROGRESS.md A5)."""
    ledger = OpsLedger()
    ledger.record(label="prior", usage=Usage(ops_charged=5))

    client, transport, _ = make_client(
        lambda *a: FakeResponse(200, {"job_id": "x"}), max_operations=5, ledger=ledger
    )
    with pytest.raises(BudgetExceeded, match="over the cap"):
        client.chat_async(message="hi", session_id="s1")

    assert transport.calls == [], "budget refusal must not hit the network"


def test_ledger_reload_preserves_spend_across_restarts(tmp_path):
    path = tmp_path / "ops.jsonl"
    first = OpsLedger(path=path)
    first.record(label="run1", usage=Usage(ops_charged=2))
    first.record(label="run1", usage=Usage(ops_charged=1))

    resumed = OpsLedger(path=path)
    resumed.load()
    assert resumed.total_ops == 3


def test_usage_defaults_to_zero_when_server_says_nothing():
    assert Usage.from_payload(None).ops_charged == 0
    assert Usage.from_payload({}).ops_charged == 0
    assert Usage.from_payload({"was_billable": True}).ops_charged == 1
    assert Usage.from_payload({"ops_charged": 3}).ops_charged == 3


# -- polling --------------------------------------------------------------


def test_poll_returns_when_awaiting_approval_and_reports_ops_once():
    pending = [{"change_id": "c1", "operation": "replace"}]
    usage = {"ops_charged": 1, "was_billable": True, "monthly_used": 7, "monthly_limit": 500}

    def handler(method, url, kwargs, n):
        if n == 0:
            return FakeResponse(200, job_payload("in_progress"))
        return FakeResponse(200, job_payload("awaiting_approval", usage=usage, pending=pending))

    client, _, printed = make_client(handler)
    job = client.poll_job("job_1", label="corpus")

    assert job["status"] == "awaiting_approval"
    assert client.ops_used == 1
    ops_lines = [p for p in printed if p.startswith("[ops]")]
    assert len(ops_lines) == 1, "usage must be reported exactly once per job"
    assert "monthly_used=7/500" in ops_lines[0]


def test_poll_ignores_a_continue_prompt_pause():
    """PLAN.md.pdf section 5's rule, honoured only when the field exists."""
    states = [
        job_payload("awaiting_approval", metadata={"awaiting_kind": "continue_prompt"}),
        job_payload("awaiting_approval", pending=[{"change_id": "c1"}]),
    ]

    def handler(method, url, kwargs, n):
        return FakeResponse(200, states[min(n, len(states) - 1)])

    client, transport, _ = make_client(handler)
    job = client.poll_job("job_1")
    assert (job.get("metadata") or {}).get("awaiting_kind") != "continue_prompt"
    assert len(transport.calls) == 2


def test_poll_raises_on_failed_job():
    client, _, _ = make_client(
        lambda *a: FakeResponse(200, job_payload("failed", error="model exploded"))
    )
    with pytest.raises(JobFailed, match="model exploded"):
        client.poll_job("job_1")


def test_poll_times_out_rather_than_hanging():
    ticks = iter([0.0, 10.0, 999.0, 1000.0])
    client, _, _ = make_client(lambda *a: FakeResponse(200, job_payload("in_progress")))
    client._clock = lambda: next(ticks)

    with pytest.raises(JobTimeout, match="in_progress"):
        client.poll_job("job_1", timeout_s=60.0)


def test_poll_returns_completed_job_without_approval_pause():
    client, _, _ = make_client(lambda *a: FakeResponse(200, job_payload("completed")))
    assert client.poll_job("job_1")["status"] == "completed"


def test_missing_usage_block_is_counted_as_spend_not_as_zero():
    """The live pilot's actual behaviour: HITL pause -> empty result, no usage.

    Recording 0 there would let the budget guard authorize further calls on
    the strength of an absent field. Over-count instead.
    """
    client, _, printed = make_client(
        lambda *a: FakeResponse(200, job_payload("awaiting_approval", pending=[{"change_id": "c1"}]))
    )
    client.poll_job("job_1", label="corpus")

    assert client.ops_used == 1, "unreported usage must not read as free"
    assert "ESTIMATED" in client.ledger.entries[-1]["note"]
    assert any("[ops]" in p for p in printed)


def test_estimated_spend_is_distinguishable_from_reported_spend():
    """The README has to report actuals; estimates must not masquerade as them."""
    usage = {"ops_charged": 1, "was_billable": True, "monthly_used": 3}
    client, _, _ = make_client(
        lambda *a: FakeResponse(200, job_payload("completed", usage=usage))
    )
    client.poll_job("job_1")

    entry = client.ledger.entries[-1]
    assert "ESTIMATED" not in entry["note"]
    assert entry["monthly_used"] == 3


def test_estimate_can_be_disabled_for_calls_known_to_be_free():
    client, _, _ = make_client(lambda *a: FakeResponse(200, job_payload("completed")))
    client.poll_job("job_1", assume_cost_if_unreported=0)
    assert client.ops_used == 0


# -- pending change extraction -------------------------------------------


def test_extract_reads_metadata_first():
    job = job_payload(pending=[{"change_id": "meta1"}])
    job["result"] = {"document_changes": {"pending_changes": [{"change_id": "other"}]}}
    assert SuperDocsClient.extract_pending_changes(job)[0]["change_id"] == "meta1"


def test_extract_falls_back_through_result_locations():
    job = {"metadata": {}, "result": {"document_changes": {"chunk_diffs": [{"change_id": "cd1"}]}}}
    assert SuperDocsClient.extract_pending_changes(job)[0]["change_id"] == "cd1"

    assert SuperDocsClient.extract_pending_changes({}) == []


def test_extract_dedupes_repeated_change_ids():
    job = job_payload(pending=[{"change_id": "c1"}, {"change_id": "c1"}, {"change_id": "c2"}])
    assert len(SuperDocsClient.extract_pending_changes(job)) == 2


# -- dotenv ---------------------------------------------------------------


def test_load_dotenv_does_not_clobber_real_environment(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text('SUPERDOCS_API_KEY="sk_from_file"\nOTHER=xyz\n', encoding="utf-8")

    monkeypatch.setenv("SUPERDOCS_API_KEY", "sk_from_shell")
    monkeypatch.delenv("OTHER", raising=False)
    load_dotenv(env)

    import os

    assert os.environ["SUPERDOCS_API_KEY"] == "sk_from_shell"
    assert os.environ["OTHER"] == "xyz"
