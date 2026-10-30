"""The failure modes that matter when this is running in somebody else's CI.

Not features -- the things that decide whether a test double is trustworthy at 2am: it
never logs a credential, it degrades with a message that names the fix, it does not
corrupt itself under concurrency, and it cannot be quietly running in a broken mode.

All offline, no key.
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from sdmock.testing import MockServer

ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.mock_only

AUTH = {"Authorization": "Bearer sk_live_pretend_this_is_real_deadbeef01234567"}


# ------------------------------------------------------------------ secrets


def test_a_key_never_reaches_the_mocks_own_logs(caplog):
    """A mock that echoes the caller's Authorization header into a log is a leak.

    CI logs are archived, searchable and often public. This sends a realistic-looking key
    through several routes and asserts the mock's own loggers stay clean.

    Scoped to `sdmock` and `uvicorn` deliberately. The first version of this test also
    captured the *test client's* logging and failed on it -- httpx logs every request URL
    at INFO, and the SSE route carries its credential in the query string. That is not
    the mock leaking, but it is a real hazard and it is written up as N-1 in
    docs/findings.md: query-string auth ends up in client logs, proxy logs and browser
    history by construction, and EventSource leaves SuperDocs no alternative.
    """
    mock_loggers = ("sdmock", "uvicorn", "uvicorn.access", "uvicorn.error", "starlette")
    with MockServer() as server, httpx.Client(base_url=server.url) as client:
        with caplog.at_level(logging.DEBUG):
            client.get("/health")
            client.post("/v1/documents/upload",
                        headers={**AUTH, "X-Mock-Scenario": "styled-document"})
            client.get("/v1/chat/s/stream",
                       params={"job_id": "j", "api_key": "sk_live_secret_in_a_query"},
                       headers={"X-Mock-Scenario": "proposed-change-batch"})
            client.post("/mcp/", headers=AUTH,
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    logged = "\n".join(
        record.getMessage() for record in caplog.records
        if record.name.split(".")[0] in {name.split(".")[0] for name in mock_loggers}
    )
    assert "sk_live_pretend" not in logged
    assert "sk_live_secret_in_a_query" not in logged


def test_responses_never_echo_the_callers_credential():
    """Not just logs -- a response body or header must not reflect the key back."""
    with MockServer() as server, httpx.Client(base_url=server.url) as client:
        for path, kwargs in [
            ("/v1/documents/upload", {"headers": {**AUTH,
                                                  "X-Mock-Scenario": "styled-document"}}),
            ("/mcp/", {"headers": AUTH,
                       "json": {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}}),
        ]:
            response = client.post(path, **kwargs)
            blob = response.text + repr(dict(response.headers))
            assert "sk_live_pretend" not in blob, path


# ------------------------------------------------------------------ degradation


def test_record_mode_without_a_key_refuses_with_a_usable_message():
    """Failing loudly beats recording a cassette full of 401s that looks fine."""
    from sdmock.record import Recorder

    environment = dict(os.environ)
    environment.pop("SUPERDOCS_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'src');"
         "from pathlib import Path;"
         "import sdmock.record as r;"
         "r.KEY_FILE = Path('/nonexistent/api-key');"
         "r.load_key()"],
        cwd=ROOT, env=environment, capture_output=True, text=True,
    )
    assert result.returncode != 0
    message = result.stderr
    assert "No API key" in message
    assert "SUPERDOCS_API_KEY" in message, "the message must name the fix"
    assert "401" in message, "and say why running without one is worse than failing"
    assert Recorder is not None


def test_an_unreachable_upstream_is_reported_as_such():
    """Record mode against a dead upstream must not look like an empty recording."""
    from sdmock.record import Recorder

    recorder = Recorder.__new__(Recorder)
    recorder.base_url = "http://127.0.0.1:1"       # nothing listens here
    recorder.key = "sk_test"
    recorder.client = httpx.Client(timeout=2)
    recorder.spent = 0
    recorder._charged = set()

    with pytest.raises(httpx.HTTPError):
        recorder._send_with_retry("GET", "http://127.0.0.1:1/v1/jobs", attempts=1)
    recorder.client.close()


def test_a_missing_cassette_directory_names_the_fix():
    from sdmock.paths import _resolve

    os.environ["SDMOCK_CASSETTES_TEST_MISSING"] = "/definitely/not/here"
    try:
        with pytest.raises(SystemExit) as caught:
            _resolve("cassettes", "SDMOCK_CASSETTES_TEST_MISSING")
        assert "not a directory" in str(caught.value)
    finally:
        del os.environ["SDMOCK_CASSETTES_TEST_MISSING"]


# ------------------------------------------------------------------ concurrency


def test_hammering_one_scenario_from_many_threads_stays_consistent():
    """Replay is read-mostly, but the cursors are shared state behind a lock.

    Sixteen threads, one scenario, one run id: every response must still be a response
    the cassette actually contains, and nothing may error.
    """
    with MockServer() as server:
        def drive(_: int) -> set[int]:
            with httpx.Client(base_url=server.url, timeout=30) as client:
                return {
                    client.get("/v1/jobs/x", headers={
                        "Authorization": "Bearer sk_test",
                        "X-Mock-Scenario": "proposed-change-batch",
                    }).status_code
                    for _ in range(12)
                }

        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(drive, range(16)))

    seen = set().union(*results)
    assert seen == {200}, f"concurrent replay produced {seen}"


def test_replay_is_idempotent_and_free():
    """Replay never bills and never mutates anything, however often it is called.

    The card asks for idempotency wherever an operation costs money. Here the guarantee
    is stronger: the read path has no cost at all, and repeating it changes nothing but
    the cursor, which `POST /__sdmock__/reset` rewinds.
    """
    with MockServer() as server, httpx.Client(base_url=server.url) as client:
        headers = {"Authorization": "Bearer sk_test",
                   "X-Mock-Scenario": "styled-document"}
        first = client.post("/v1/documents/upload", headers=headers).content
        for _ in range(20):
            assert client.post("/v1/documents/upload", headers=headers).content == first


# ------------------------------------------------------------------ posture


def test_the_mock_is_not_secretly_running_a_mutant():
    """A broken mock must never be mistaken for a faithful one."""
    from sdmock import mutants

    assert not os.environ.get(mutants.MUTANT_ENV)
    with MockServer() as server, httpx.Client(base_url=server.url) as client:
        response = client.post("/v1/documents/upload", headers={
            "Authorization": "Bearer sk_test", "X-Mock-Scenario": "styled-document"})
        assert "x-mock-mutant" not in response.headers


def test_every_response_identifies_the_scenario_it_came_from():
    """When a test fails at 2am, the response should say which fixture produced it."""
    with MockServer() as server, httpx.Client(base_url=server.url) as client:
        response = client.post("/v1/documents/upload", headers={
            "Authorization": "Bearer sk_test", "X-Mock-Scenario": "styled-document"})
        assert response.headers["x-mock-scenario"] == "styled-document"
        assert response.headers["x-mock-interaction"].startswith("i-")


def test_the_drift_watcher_can_actually_see_drift():
    """A watcher that has never been shown detecting anything is a cron entry.

    Same argument as the kill matrix, applied to the thing that guards the pins.
    """
    import json

    sys.path.insert(0, str(ROOT / "scripts"))
    from watch_surface import diff_spec

    pinned = json.loads((ROOT / "spec" / "openapi.json").read_text(encoding="utf-8"))

    unchanged = diff_spec(pinned, pinned)
    assert not any(unchanged[k] for k in
                   ("routes_added", "routes_removed", "schemas_added",
                    "schemas_removed", "schemas_changed"))

    removed = json.loads(json.dumps(pinned))
    removed["paths"].pop("/v1/chat/async")
    assert "POST /v1/chat/async" in diff_spec(removed, pinned)["routes_removed"]

    retyped = json.loads(json.dumps(pinned))
    retyped["components"]["schemas"]["PendingChange"]["properties"]["change_id"]["type"] \
        = "integer"
    assert "PendingChange" in diff_spec(retyped, pinned)["schemas_changed"]
