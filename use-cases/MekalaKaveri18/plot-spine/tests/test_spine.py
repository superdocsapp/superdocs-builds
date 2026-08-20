import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from spine import MANUSCRIPT, find_breaks, hashes, offline_repair


def test_manuscript_injection_is_data():
    kinds = {b["kind"] for b in find_breaks(MANUSCRIPT)}
    assert "document_injection" in kinds
    assert "dead_character_onstage" in kinds
    assert "place_bearing" in kinds


def test_repair_keeps_earlier_chapters_byte_identical():
    before = hashes(MANUSCRIPT)
    after_html = offline_repair(MANUSCRIPT)
    after = hashes(after_html)
    assert before["chapter-3"] == after["chapter-3"]
    assert before["chapter-8"] == after["chapter-8"]
    assert before["chapter-12"] != after["chapter-12"]
    assert "waved" not in after_html.split("chapter-12")[-1].lower()
    assert "northern quay" in after_html.split("chapter-12")[-1].lower()
    assert "Mara Vale had died" in after_html
