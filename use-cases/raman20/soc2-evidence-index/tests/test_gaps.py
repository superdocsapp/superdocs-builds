import json

from tests.conftest import FIXTURES, build_from


def test_sample_gaps(sample_catalog):
    index, _, _ = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    ids = {r.row_id for r in index.rows}
    expected = json.loads((FIXTURES / "expected/sample/v1.row_ids.json").read_text())
    assert ids == set(expected)
    gap = next(r for r in index.rows if r.row_id == "CC7.2::gap::none")
    assert gap.gap_reason
    assert gap.source_path is None
    assert {r.control_id for r in index.rows} == set(sample_catalog.ids)


def test_full_gaps(full_catalog):
    index, _, _ = build_from(FIXTURES / "cedar-harbor-v1", full_catalog)
    present = {r.row_id for r in index.rows if r.status == "Present"}
    expected_present = set(json.loads((FIXTURES / "expected/cc/v1.row_ids.json").read_text()))
    assert present == expected_present
    assert len(index.rows) == 33
    assert index.coverage.gap_rows == 25
    assert index.coverage.present_rows == 8
    ids = {r.row_id for r in index.rows}
    assert "CC7.2::gap::none" in ids
    assert "CC1.1::gap::none" in ids


def test_clean_zero_gaps(sample_catalog):
    index, _, mapping = build_from(FIXTURES / "cedar-harbor-clean", sample_catalog)
    cov = index.coverage
    expected = json.loads((FIXTURES / "expected/clean/sample.coverage.json").read_text())
    assert cov.gap_rows == 0
    assert cov.present_controls == 13
    assert cov.present_control_ids == expected["present_control_ids"]
    assert cov.present_rows == 13
    assert mapping.ambiguous == []
    assert mapping.flagged == []
