import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from letter import commitments, draft_letter, hedges, load_thread


def test_dated_send_is_a_commitment():
    payload = load_thread()
    html = draft_letter(payload)
    found = commitments(payload)
    assert any("28 August 2026" in c for c in found)
    assert "redlined MSA" in html
    assert "28 August 2026" in html


def test_hedging_is_not_a_deadline():
    payload = load_thread()
    html = draft_letter(payload)
    assert hedges(payload)
    block = html.split("Commitments")[1].split("Not commitments")[0].lower()
    assert "28 august 2026" in block
    assert "soon" not in block
    assert "maybe" not in block
    assert "not recorded as promises" in html.lower()
