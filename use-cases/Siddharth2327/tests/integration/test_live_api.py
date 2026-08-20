"""Real end-to-end test against the LIVE SuperDocs API.

Distinct from tests/unit/: this file makes real network calls and spends real
operations against your SuperDocs account. It is auto-skipped unless
SUPERDOCS_API_KEY is set, so `pytest` (no args) never accidentally hits the network
or bills your account.

Run explicitly with:
    SUPERDOCS_API_KEY=sk_... pytest tests/integration -m integration -v

This has not been run by the agent that built this project -- no API key was
available (see progress.md). It is written strictly to the documented contract and
is expected to work, but "expected" is not the same as "verified live." Run it
yourself before relying on this in a demo.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from winloss_superdocs.client import SuperDocsClient
from winloss_superdocs.config import load_settings
from winloss_superdocs.debrief import create_debrief
from winloss_superdocs.index import Index
from winloss_superdocs.review import auto_approve_all

pytestmark = pytest.mark.integration

requires_live_key = pytest.mark.skipif(
    not os.environ.get("SUPERDOCS_API_KEY"),
    reason="SUPERDOCS_API_KEY not set -- real integration test skipped by design",
)


@requires_live_key
def test_live_debrief_end_to_end(tmp_path):
    settings = load_settings()
    client = SuperDocsClient(settings, api_key=settings.api_key)
    index = Index(tmp_path / "index.json")

    transcript = tmp_path / "smoke_test.txt"
    transcript.write_text(
        "Call with Test Customer LLC.\n"
        "Customer: We chose you over Rival Inc mainly because of better uptime SLAs.\n"
        "Customer: Pricing was roughly comparable between the two options.\n"
        "Customer: The deciding factor was your 99.99% uptime guarantee.\n"
    )

    result = create_debrief(
        client,
        index,
        transcript_path=transcript,
        deal_code="SMOKE-TEST-001",
        quarter="2099Q1",
        segment="Test",
        outcome="win",
        customer_name="Test Customer LLC",
        output_dir=tmp_path / "out",
        approval_callback=auto_approve_all,
    )

    assert result.exported_path.exists()
    assert result.exported_path.stat().st_size > 0

    docs = client.list_documents()
    assert "documents" in docs
    print(f"\nLive smoke test spent {client.usage.ops_used} operation(s).")
