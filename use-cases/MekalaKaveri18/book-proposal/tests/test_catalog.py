import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "_lib"))
sys.path.insert(0, str(ROOT))

from catalog import search_comparables
from superdocs import parse_pending_changes


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
