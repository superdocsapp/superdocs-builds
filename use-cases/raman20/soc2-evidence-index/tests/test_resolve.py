from pathlib import Path

from tests.conftest import FIXTURES, build_from


def test_present_resolves_sample(sample_catalog):
    index, files, _ = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    by_path = {f.relative_path: f for f in files}
    present = [r for r in index.rows if r.status == "Present"]
    assert present
    for row in present:
        rec = by_path[row.source_path]
        assert rec.sha256 == row.sha256
        assert (FIXTURES / "cedar-harbor-v1" / row.source_path).is_file()


def test_present_resolves_full(full_catalog):
    index, files, _ = build_from(FIXTURES / "cedar-harbor-v1", full_catalog)
    by_path = {f.relative_path: f for f in files}
    for row in index.rows:
        if row.status != "Present":
            continue
        rec = by_path[row.source_path]
        assert rec.sha256 == row.sha256
        assert Path(FIXTURES / "cedar-harbor-v1" / row.source_path).is_file()
