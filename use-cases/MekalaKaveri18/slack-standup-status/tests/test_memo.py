import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from memo import draft_memo, load_standup, search_playbook


def test_memo_does_not_promise_lucky_friday():
    html = draft_memo(load_standup())
    assert "Harbor & Pine" in html
    assert "2026-08-22" in html
    assert "lucky" not in html.lower()
    assert "friday" not in html.lower()
    assert "IdP" in html or "metadata" in html.lower()


def test_playbook_search_hits_ciso_rule():
    hits = search_playbook("ciso forward")
    assert any("CISO" in h for h in hits)
