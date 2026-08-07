"""The 4-call filing flow against the mock server: upload -> chat (approval
gate) -> approve -> export, as one paginated artifact."""

from __future__ import annotations

import pytest

from exhibit import proposals
from exhibit.flow import build_message, run_filing, PROPOSAL_OPEN, PROPOSAL_CLOSE
from exhibit.mock_server import start_server
from exhibit.superdocs import SuperDocsClient


@pytest.fixture()
def client():
    base, stop, _state = start_server()
    yield SuperDocsClient(base_url=base, api_key="sk_mock")
    stop.set()


def test_build_message_embeds_machine_readable_proposal(sample_items):
    import json

    prop = proposals.propose("A brief about evidence.", sample_items)
    message = build_message("A brief about evidence.", prop)
    assert PROPOSAL_OPEN in message and PROPOSAL_CLOSE in message
    payload = json.loads(message.split(PROPOSAL_OPEN)[1].split(PROPOSAL_CLOSE)[0])
    assert len(payload["exhibits"]) == len(prop.set)
    assert len(payload["citations"]) == len(prop.citations)


def test_run_filing_four_call_contract(client, sample_brief, sample_items):
    prop = proposals.propose(sample_brief, sample_items)
    result = run_filing(client, sample_brief, prop, fmt="html")
    assert result.session_id and result.job_id
    assert len(result.approved) > 0
    assert len(result.denied) == 0
    text = result.export.content.decode("utf-8", errors="replace")
    # every exhibit's citation made it into the exported document
    for ex in prop.set:
        assert f"[See Exhibit {ex.number}]" in text
    assert result.export.filename and result.export.filename.endswith(".html")


def test_run_filing_export_matches_renumbered_set(client, sample_brief, sample_items):
    """Late insertion renumbers the set; the export must carry the new numbers."""
    from pathlib import Path

    prop = proposals.propose(sample_brief, sample_items)
    prop.set.add(source=Path("new.pdf"), title="New Evidence",
                 proves="Evidences the new matter.", content="new\nmatter",
                 after=2)
    prop.repropose(sample_brief)

    result = run_filing(client, sample_brief, prop, fmt="html")
    text = result.export.content.decode("utf-8", errors="replace")
    for ex in prop.set:
        assert f"[See Exhibit {ex.number}]" in text
