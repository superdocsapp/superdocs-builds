"""Mac-helper bridge logic tests (P2).

Covers the Python control-process glue: backend-origin derivation from the
WSS URL, and the CaptureRunner spawn/duplicate-ignore/SIGTERM lifecycle
(driven against a harmless `/bin/sleep` stand-in for the Swift binary — the
Swift capture itself is exercised live, not in pytest).

The /audio → Groq → transcript-event path is covered by the existing suite
(test_groq_client, test_manual_provider, test_routes_audio behavior).
"""

import os
import signal
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "helper"))
from helper import CaptureRunner, derive_backend  # noqa: E402


def test_derive_backend_wss_to_https():
    assert derive_backend("wss://live-deliverable-zoom-app-production.up.railway.app/api/ws/helper") == (
        "https://live-deliverable-zoom-app-production.up.railway.app"
    )


def test_derive_backend_ws_to_http():
    assert derive_backend("ws://localhost:8010/api/ws/helper") == "http://localhost:8010"


def test_capture_runner_start_stop_lifecycle():
    runner = CaptureRunner(backend="http://localhost:8010")
    runner.binary = "/bin/sleep"  # stand-in for the Swift binary

    assert runner.start("meeting-abc") is True
    assert runner.capturing is True

    # Duplicate START while capturing is ignored (returns True, no respawn).
    assert runner.start("meeting-xyz") is True
    assert runner.capturing is True
    assert runner.uuid == "meeting-abc"  # unchanged by the duplicate

    runner.stop()
    assert runner.capturing is False
    assert runner.proc is None


def test_capture_runner_missing_binary_reports_failure():
    runner = CaptureRunner(backend="http://localhost:8010")
    runner.binary = "/nonexistent/no-such-binary"
    assert runner.start("meeting-abc") is False
    assert runner.capturing is False
