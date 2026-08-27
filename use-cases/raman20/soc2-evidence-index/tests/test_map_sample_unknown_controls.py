from tests.conftest import FIXTURES, build_from


def test_sample_unknown_controls(sample_catalog, caplog):
    index, files, mapping = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    ids = {r.row_id for r in index.rows}
    assert not any("CC5.3" in i for i in ids)
    assert not any("CC8.1" in i for i in ids)
    unmapped = {u.relative_path: u.reason for u in mapping.unmapped}
    assert unmapped.get("policy/POL-ISMS-001.md") == "controls_not_in_catalog"
    assert unmapped.get("change/CHG-1042.md") == "no_rule"
    acc = [r for r in index.rows if r.status == "Present" and r.source_path and "ACC-REV" in r.source_path]
    assert len(acc) == 3
    assert len({r.row_id for r in acc}) == 3
