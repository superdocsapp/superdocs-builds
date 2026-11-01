from soc2_index.models import Proof
from soc2_index.validate import live_ok


def test_live_ok_row_set_not_chunk_ids():
    p = Proof(
        catalog_id="tsc-cc6-cc7",
        present_rows=6,
        present_resolved=6,
        dangling=[],
        gap_rows=7,
        html_row_ids=["CC6.1::present::x"],
        html_missing_gaps=[],
        invented=[],
        overreach=["unmapped_chunk:CC6.1::present::x"],
    )
    assert live_ok(p) is True


def test_live_ok_fails_invented():
    p = Proof(
        catalog_id="tsc-cc6-cc7",
        present_rows=1,
        present_resolved=1,
        dangling=[],
        gap_rows=0,
        html_missing_gaps=[],
        invented=["CC9.9::present::nope.md"],
    )
    assert live_ok(p) is False
