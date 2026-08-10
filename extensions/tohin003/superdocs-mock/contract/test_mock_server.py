"""The properties the mock itself must hold, independent of what it is mocking.

These are not contract tests against SuperDocs -- those arrive in the next phase and run
against both targets. These assert the things a test double has to get right before its
opinions about anything else are worth reading: it starts fast, it answers identically
every time, two runs do not corrupt each other, and it never invents a response.

All of it runs with no API key and no network.
"""

from __future__ import annotations

import concurrent.futures
import json
import time

import httpx
import pytest

from sdmock.testing import MockServer

AUTH = {"Authorization": "Bearer sk_test_anything"}


@pytest.fixture(scope="module")
def mock():
    with MockServer() as server:
        yield server


@pytest.fixture()
def client(mock):
    mock.reset()
    with httpx.Client(base_url=mock.url, timeout=30) as c:
        yield c


def scenario(name: str, **extra: str) -> dict[str, str]:
    return {**AUTH, "X-Mock-Scenario": name, **extra}


# ------------------------------------------------------------------ it starts fast


def test_starts_in_well_under_a_second():
    """The card asks for a mock that starts in under a second.

    Measured as process-free as possible: server object to first accepted connection.
    The published benchmark in Phase 5 measures cold process start as well, which is the
    number that actually matters to CI; this is the guard that keeps it from regressing.
    """
    elapsed = []
    for _ in range(3):
        server = MockServer()
        server.start()
        elapsed.append(server.startup_seconds)
        server.stop()
    worst = max(elapsed)
    assert worst < 1.0, f"slowest start {worst:.3f}s exceeds the one-second bar"


# ------------------------------------------------------------------ determinism


def test_identical_requests_are_byte_identical(client):
    """Determinism is a feature: a flaky fixture is worse than no fixture."""
    digests = set()
    for _ in range(3):
        client.post("/__sdmock__/reset")
        response = client.post(
            "/v1/chat/async",
            headers=scenario("proposed-change-batch"),
            json={"message": "anything", "session_id": "s"},
        )
        digests.add(response.content)
    assert len(digests) == 1, "the same request produced different bytes across runs"


def test_full_journey_is_byte_identical_across_runs(client):
    """Not just one call -- a whole replayed journey has to be reproducible."""
    def journey() -> list[bytes]:
        client.post("/__sdmock__/reset")
        out = []
        out.append(client.post("/v1/documents/upload",
                               headers=scenario("styled-document")).content)
        started = client.post("/v1/chat/async", headers=scenario("proposed-change-batch"),
                              json={"message": "x", "session_id": "s"})
        out.append(started.content)
        job_id = started.json()["job_id"]
        out.append(client.get(f"/v1/jobs/{job_id}",
                              headers=scenario("proposed-change-batch")).content)
        out.append(client.post("/v1/documents/export", headers=scenario("export-docx"),
                               json={"session_id": "s", "format": "docx"}).content)
        return out

    assert journey() == journey() == journey()


# ------------------------------------------------------------------ concurrency


def test_two_scenarios_in_parallel_do_not_cross_contaminate(mock):
    """Concurrent work must not corrupt state.

    Two scenarios are driven at once from separate threads. Each must see only its own
    recordings -- a shared cursor would hand one thread the other's response.
    """
    def drive(name: str, expected_status: int, rounds: int = 12) -> list[int]:
        with httpx.Client(base_url=mock.url, timeout=30) as c:
            return [
                c.post("/v1/chat", headers=scenario(name),
                       json={"message": "x", "session_id": "s"}).status_code
                for _ in range(rounds)
            ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        surge = pool.submit(drive, "rate-limit-surge", 429)
        quota = pool.submit(drive, "rate-limit", 429)
        surge_codes, quota_codes = surge.result(), quota.result()

    assert set(surge_codes) == {429} and set(quota_codes) == {429}

    with httpx.Client(base_url=mock.url, timeout=30) as c:
        surge_body = c.post("/v1/chat", headers=scenario("rate-limit-surge"),
                            json={"message": "x", "session_id": "s"})
        quota_body = c.post("/v1/chat", headers=scenario("rate-limit"),
                            json={"message": "x", "session_id": "s"})
    # The two 429s are materially different, which is the point of keeping them apart.
    assert surge_body.headers.get("retry-after") is None
    assert quota_body.headers.get("retry-after") == "1209600"


def test_same_scenario_twice_over_keeps_separate_cursors(mock):
    """Two independent runs of one scenario, isolated by X-Mock-Run.

    Without this, two CI jobs sharing a mock would consume each other's job-state
    transitions and see a polling loop skip straight to completed.
    """
    def poll_sequence(run: str) -> list[str]:
        with httpx.Client(base_url=mock.url, timeout=30) as c:
            return [
                c.get("/v1/jobs/any", headers=scenario("proposed-change-batch",
                                                       **{"X-Mock-Run": run})).text
                for _ in range(4)
            ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(poll_sequence, "run-a")
        b = pool.submit(poll_sequence, "run-b")
        assert a.result() == b.result(), (
            "two isolated runs of one scenario saw different sequences"
        )


# ------------------------------------------------------------------ honesty


def test_unknown_scenario_names_the_cause_and_lists_the_catalogue(client):
    response = client.get("/v1/jobs/x", headers=scenario("no-such-scenario"))
    assert response.status_code == 400
    body = response.json()
    assert "no-such-scenario" in body["detail"]
    assert body["sdmock"]["fix"]
    assert "styled-document" in body["sdmock"]["available"]


def test_route_absent_from_the_spec_is_a_404_not_a_guess(client):
    response = client.get("/v1/definitely-not-a-route", headers=AUTH)
    assert response.status_code == 404
    assert "pinned specification" in response.json()["sdmock"]["fix"]


def test_unrecorded_route_refuses_rather_than_inventing(client):
    """A spec route this scenario never captured returns 501, never a plausible body."""
    response = client.get("/v1/templates", headers=scenario("styled-document"))
    assert response.status_code == 501
    fix = response.json()["sdmock"]["fix"]
    assert "never invents" in fix


def test_synthesised_cassettes_are_flagged_on_every_response(client):
    """A reconstruction announces itself at the point of use, not only in the docs."""
    synthesised = client.post("/v1/chat", headers=scenario("rate-limit"),
                              json={"message": "x", "session_id": "s"})
    recorded = client.post("/v1/documents/upload", headers=scenario("styled-document"))
    assert synthesised.headers.get("x-mock-synthesised") == "true"
    assert recorded.headers.get("x-mock-synthesised") is None


def test_missing_auth_reproduces_the_documented_401(client):
    """B-002: a client's auth-failure path deserves testing too."""
    response = client.post("/v1/chat", json={"message": "x", "session_id": "s"})
    assert response.status_code == 401
    assert response.json()["detail"].startswith("Invalid authorization header format")


# ------------------------------------------------------------------ portability


def test_cassettes_replay_for_a_client_using_its_own_ids(client):
    """The recordings were captured against sdmock-* ids; anyone's ids must work.

    Path templating comes from the pinned spec, so /v1/chat/{session_id}/approve matches
    whatever session id the caller chose. Without this the mock would only ever work for
    the person who recorded it.
    """
    for index, session in enumerate(("my-app-session-42", "tenant_9.prod", "a-b-c")):
        # A separate run per session, so each starts at the top of the recorded
        # sequence. Sharing a cursor here would test cursor behaviour, not portability.
        response = client.post(
            f"/v1/chat/{session}/approve",
            headers=scenario("proposed-change-batch", **{"X-Mock-Run": f"r{index}"}),
            json={"job_id": "whatever", "changes": [{"change_id": "c1"}]},
        )
        assert response.status_code == 422, (
            f"session id {session!r} did not match the recorded template"
        )
        assert response.json()["detail"][0]["loc"] == ["body", "approved"]


# ------------------------------------------------------------------ streaming


def test_last_sequence_replays_only_newer_events(client):
    """B-056/B-057: resume returns strictly fewer frames as the cursor advances."""
    def frames(last: int | None) -> list[int]:
        params = {"job_id": "j", "api_key": "sk_test"}
        if last is not None:
            params["last_sequence"] = str(last)
        response = client.get("/v1/chat/s/stream", params=params,
                              headers=scenario("proposed-change-batch"))
        assert response.status_code == 200
        return [
            json.loads(line[6:]).get("sequence")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        ]

    full = frames(None)
    assert full, "no frames recorded"
    for cutoff in (2, 5, 9):
        resumed = frames(cutoff)
        assert all(seq > cutoff for seq in resumed), resumed
        assert len(resumed) < len(full)


def test_stream_reproduces_the_duplicate_sequence_faithfully(client):
    """Finding F-006, preserved rather than tidied away.

    The live service emits two different events sharing sequence 11, which means a client
    resuming from 11 never receives `final`. The mock reproduces that exactly, so an
    integrator can write a regression test for their own workaround against a fixture
    instead of against production.
    """
    response = client.get("/v1/chat/s/stream", params={"job_id": "j", "api_key": "k"},
                          headers=scenario("proposed-change-batch"))
    sequences = [
        json.loads(line[6:]).get("sequence")
        for line in response.text.splitlines() if line.startswith("data: ")
    ]
    assert len(sequences) != len(set(sequences)), (
        "the duplicate sequence has gone -- either the cassette was re-recorded against "
        "a fixed service (update F-006) or the mock is now tidying it away (do not)"
    )

    duplicated = next(s for s in sequences if sequences.count(s) > 1)
    after = client.get("/v1/chat/s/stream",
                       params={"job_id": "j", "api_key": "k",
                               "last_sequence": str(duplicated)},
                       headers=scenario("proposed-change-batch"))
    events = [line[7:].strip() for line in after.text.splitlines()
              if line.startswith("event: ")]
    assert "final" not in events, (
        "the failure mode F-006 describes is no longer reproducible"
    )


# ------------------------------------------------------------------ MCP transport


def rpc(client: httpx.Client, method: str, params=None, *, scenario_name=None, rpc_id=1):
    headers = dict(AUTH)
    if scenario_name:
        headers["X-Mock-Scenario"] = scenario_name
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp/", json=body, headers=headers)


def test_mcp_and_rest_are_served_on_the_same_port(client):
    """Mirroring the real service: one origin, one bearer token, both surfaces."""
    assert client.get("/health").status_code == 200
    assert rpc(client, "initialize", {"protocolVersion": "2025-06-18",
                                      "capabilities": {},
                                      "clientInfo": {"name": "t", "version": "1"}}
               ).status_code == 200


def test_mcp_advertises_the_pinned_surface(client):
    """38 tools and 4 prompts, from the Phase 1 pin rather than a retyped subset."""
    tools = rpc(client, "tools/list", {}).json()["result"]["tools"]
    prompts = rpc(client, "prompts/list", {}).json()["result"]["prompts"]
    assert len(tools) == 38, f"expected the pinned 38 tools, got {len(tools)}"
    assert len(prompts) == 4
    assert {p["name"] for p in prompts} == {
        "convert_format", "draft_from_outline",
        "edit_styled_docx", "review_contract_for_redflags",
    }


def test_mcp_handshake_carries_instructions(client):
    """B-096: agents read this on connect; a mock that drops it changes their behaviour."""
    result = rpc(client, "initialize", {"protocolVersion": "2025-06-18",
                                        "capabilities": {},
                                        "clientInfo": {"name": "t", "version": "1"}}
                 ).json()["result"]
    assert result.get("instructions")
    assert result["serverInfo"]["name"].endswith("(sdmock replay)"), (
        "the mock must not impersonate the real server in its own handshake"
    )


def test_mcp_notification_is_acknowledged_without_a_body(client):
    assert rpc(client, "notifications/initialized").status_code == 202


def test_mcp_tool_call_resolves_through_the_shared_replay_core(client):
    """D7: one cassette, two transports.

    `chat_async` was never recorded over MCP. It resolves through the same Library the
    REST app uses, so both transports return the same job -- which is what makes the
    parity test in the next phase meaningful rather than circular.
    """
    over_mcp = rpc(client, "tools/call",
                   {"name": "chat_async",
                    "arguments": {"message": "x", "session_id": "s"}},
                   scenario_name="proposed-change-batch").json()["result"]
    client.post("/__sdmock__/reset")
    over_rest = client.post("/v1/chat/async", headers=scenario("proposed-change-batch"),
                            json={"message": "x", "session_id": "s"}).json()

    assert over_mcp["structuredContent"]["job_id"] == over_rest["job_id"]
    assert over_mcp["isError"] is False


def test_mcp_refuses_an_unbacked_tool_instead_of_inventing_one(client):
    result = rpc(client, "tools/call",
                 {"name": "revert_session_to_message", "arguments": {}},
                 scenario_name="mcp-journey").json()["result"]
    assert result["isError"] is True
    assert "never invents" in result["content"][0]["text"]


def test_mcp_unknown_method_returns_a_jsonrpc_error(client):
    error = rpc(client, "completion/complete", {}).json()["error"]
    assert error["code"] == -32601
