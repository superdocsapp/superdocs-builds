"""Suite-wide setup.

The fake reads ``FAKE_STATE_DIR`` so that the API container and the worker container share
one SuperDocs, the way both would share a real one; compose sets it for both services. A test
must not inherit that. It runs in the same image, so the variable is present, and the suite
would quietly start sharing sessions and jobs between test cases through a file on a volume —
where a test's result depends on what ran before it, and on what a previous *run* left
behind.

Cleared once, here, so the tests are hermetic wherever they run: inside compose, in CI, or on
a developer's machine that happens to export it.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_fake_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test gets a fake that remembers nothing but what the test told it."""
    monkeypatch.delenv("FAKE_STATE_DIR", raising=False)


@pytest.fixture(autouse=True)
def never_spend_money(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """No test may reach the live service, whatever the shell it was started from.

    `PROVIDER` and `SUPERDOCS_API_KEY` are ordinary environment variables that compose passes
    straight through, so running the suite from a terminal set up for a live run — which is
    exactly the terminal you are in while checking a live run — would point every test at the
    real API and charge for it. The suite is supposed to be the thing a stranger can run
    without spending anything.

    Pinned rather than merely unset: `PROVIDER` unset already means fake, but saying so leaves
    nothing to interpretation, and the key is cleared so a mistake fails loudly instead of
    billing quietly.

    A test marked ``live`` is exempt, and that exemption is the point rather than a hole in
    the rule: it is opted into by name, it never runs in the keyless suite, and taking its key
    away would not have made anything safer — it would have turned a test that reproduces a
    real finding into one that skips in silence.
    """
    if request.node.get_closest_marker("live") is not None:
        return
    monkeypatch.setenv("PROVIDER", "fake")
    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
