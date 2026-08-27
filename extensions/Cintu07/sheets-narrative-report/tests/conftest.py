"""Shared fixtures.

Everything here runs offline. No test in this suite needs an API key, a network
connection, or a paid operation, that is a hard requirement of the brief and
also the only way the suite is worth running on every change.
"""

from __future__ import annotations

import pytest
from fakes import QUARTERLY, FakeClient

from narrative_report.superdocs import ProposedChange


@pytest.fixture
def quarterly():
    return [row[:] for row in QUARTERLY]


@pytest.fixture
def fake_client():
    return FakeClient()


@pytest.fixture
def store(tmp_path):
    from narrative_report.store import ReportStore

    return ReportStore(tmp_path / "reports")


@pytest.fixture
def pending_change():
    return ProposedChange(
        change_id="ch_1",
        operation="edit",
        chunk_id="chunk-a",
        old_html="<p>old</p>",
        new_html="<p>new</p>",
        ai_explanation="because",
    )
