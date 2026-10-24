"""
Regression tests for the production WIRING, not for workflow logic.

These exist because the original silent-stale-version bug lived entirely in
app/main.py and was structurally invisible to every other test in this suite:
tests/conftest.py wires the TestClient with `get_workflow=lambda: workflow` -
a singleton - while app.main.get_workflow() returned a NEW DocumentWorkflow on
every single request. DocumentWorkflow carries per-checkout state across four
separate HTTP calls (checkout -> edit -> review -> checkin), so a fresh
instance per request meant that state was empty every time it was read.

The visible symptom was: check in an approved edit, get HTTP 200 and a new
version number, and find the new version byte-identical to the old one. No
error, anywhere, at any layer.

test_get_workflow_is_a_singleton is the one that fails on the original code.
"""
from __future__ import annotations

import app.main as main
from app.services.workflow import DocumentWorkflow


def test_get_workflow_is_a_singleton(monkeypatch):
    """
    DocumentWorkflow's per-checkout state must survive across requests, so
    every request must get the SAME instance. Returning a new one per call
    silently empties _checkout_baseline_html and _approved_sessions between
    checkout, edit, review and checkin.
    """
    monkeypatch.setattr(main, "_workflow", None)
    monkeypatch.setattr(main, "_superdocs_client", object())

    first = main.get_workflow()
    second = main.get_workflow()

    assert isinstance(first, DocumentWorkflow)
    assert first is second, (
        "get_workflow() must return a singleton - a per-request instance loses "
        "the checkout state that checkin() depends on"
    )


def test_get_dms_is_a_singleton():
    """The DMS store holds all versions; a per-request store would lose them."""
    assert main.get_dms() is main.get_dms()


def test_workflow_shares_the_singleton_dms(monkeypatch):
    """
    The singleton workflow must be wired to the singleton store, or check-ins
    would be written to a store nothing else reads.
    """
    monkeypatch.setattr(main, "_workflow", None)
    monkeypatch.setattr(main, "_superdocs_client", object())

    assert main.get_workflow()._dms is main.get_dms()
