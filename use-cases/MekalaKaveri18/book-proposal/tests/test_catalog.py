import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_lib"))
sys.path.insert(0, str(ROOT))

from catalog import search_comparables
from superdocs import parse_pending_changes


def test_proposal_body_waits_for_approve():
    from app import JOBS, DecisionIn, ProposalIn, review, start

    JOBS.clear()
    body = ProposalIn(
        title="Attention is a Practice",
        author="Mira Ellison",
        overview="A book on attention.",
        audience="productivity knowledge workers",
        chapters="One\nTwo",
        review_mode=True,
        sample=True,
    )
    first = start(body)
    assert first["status"] == "awaiting_approval"
    assert "Attention is a Practice" not in first["html"]
    assert len(first["changes"]) == 6

    title = review(first["id"], DecisionIn(decisions={"title": True}))
    assert title["status"] == "awaiting_approval"
    assert "Attention is a Practice" in title["html"]
    assert "[Overview to be filled]" in title["html"]

    overview = review(first["id"], DecisionIn(decisions={"overview": False}))
    assert "A book on attention." not in overview["html"]
    assert "[Overview to be filled]" in overview["html"]
    assert overview["status"] == "awaiting_approval"

    rest = overview
    for c in list(overview["changes"]):
        rest = review(first["id"], DecisionIn(decisions={c["change_id"]: True}))
    assert rest["status"] == "completed"
    assert "Attention is a Practice" in rest["html"]
    assert "[Overview to be filled]" in rest["html"]


def test_search_returns_specific_real_titles():
    hits = search_comparables("productivity knowledge workers", limit=3)
    titles = {h["title"] for h in hits}
    assert "Deep Work" in titles or "Atomic Habits" in titles
    assert all(h.get("isbn") and h.get("publisher") for h in hits)
    assert "generic bestseller" not in json.dumps(hits).lower()


def test_pending_changes_second_parse():
    encoded = json.dumps(
        [
            {
                "change_id": "ch_1",
                "operation": "edit",
                "new_html": "<p>Market</p>",
                "ai_explanation": "comps",
            }
        ]
    )
    job = {"metadata": json.dumps({"pending_changes": encoded})}
    changes = parse_pending_changes(job)
    assert changes[0]["change_id"] == "ch_1"
    assert changes[0]["new_html"]
