from soc2_index.paths import project_root
from soc2_index.superdocs.parse_index import parse

HTML = (project_root() / "fixtures/superdocs/index_filled.html").read_text(encoding="utf-8")


def test_parse_index_identities():
    parsed = parse(HTML)
    by = {r.row_id: r for r in parsed.rows}
    assert "CC6.1::present::access/ACC-REV-2025-Q1.md" in by
    acc = by["CC6.1::present::access/ACC-REV-2025-Q1.md"]
    assert acc.tr_chunk_id == "tr-acc"
    assert acc.tr_chunk_id != "td-acc-1"
    assert by["CC7.2::gap::none"].tr_chunk_id == "tr-gap"
    assert "CC7.2::gap::—" not in by
    assert "CC6.5::present::access/PHYS-2025-01.md" in by
    assert parsed.row_chunk_map["CC7.2::gap::none"] == "tr-gap"
