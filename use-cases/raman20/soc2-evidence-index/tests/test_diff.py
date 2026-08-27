import json

from soc2_index.diff import compute
from tests.conftest import FIXTURES, build_from


def test_sample_diff(sample_catalog):
    v1, _, _ = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    v2, _, _ = build_from(FIXTURES / "cedar-harbor-v2", sample_catalog)
    d = compute(v1, v2, "runs/v1", "runs/v2")
    golden = json.loads((FIXTURES / "expected/sample/v2.diff.json").read_text())
    assert set(d.added) == set(golden["added"])
    assert set(d.removed) == set(golden["removed"])
    assert {c.row_id for c in d.changed} == set(golden["changed_ids"])
    assert set(d.unchanged_ids) == set(golden["unchanged"])
    assert d.summary == golden["summary"]
    for ch in d.changed:
        assert set(ch.fields) >= {"date", "evidence_title", "sha256"}


def test_full_diff(full_catalog):
    v1, _, _ = build_from(FIXTURES / "cedar-harbor-v1", full_catalog)
    v2, _, _ = build_from(FIXTURES / "cedar-harbor-v2", full_catalog)
    d = compute(v1, v2, "runs/v1", "runs/v2")
    golden = json.loads((FIXTURES / "expected/cc/v2.diff.json").read_text())
    assert set(d.added) == set(golden["added"])
    assert set(d.removed) == set(golden["removed"])
    assert {c.row_id for c in d.changed} == set(golden["changed_ids"])
    assert d.summary["unchanged"] == 29
    for rid in golden["unchanged_includes"]:
        assert rid in d.unchanged_ids
