from soc2_index.extract import parse_front_matter
from soc2_index.ingest import walk
from soc2_index.map import apply
from tests.conftest import FIXTURES


def test_inject_never_present(sample_catalog):
    files = walk(FIXTURES / "cedar-harbor-v1")
    inject = next(f for f in files if "INJECT" in f.relative_path)
    assert inject.injection_flags
    mapping = apply(sample_catalog, files)
    for row in mapping.rows:
        if row.status == "Present":
            assert "INJECT" not in (row.source_path or "")
    assert any("INJECT" in f.relative_path for f in mapping.flagged)


def test_inject_even_with_controls_key(sample_catalog, tmp_path):
    src = (FIXTURES / "cedar-harbor-v1/ops/INJECT-ignore-instructions.md").read_text()
    fm, body, _ = parse_front_matter("---\ncontrols: [CC6.1]\n---\n" + src)
    dest = tmp_path / "INJECT-ignore-instructions.md"
    dest.write_text("---\ncontrols: [CC6.1]\n---\n" + src, encoding="utf-8")
    files = walk(tmp_path)
    mapping = apply(sample_catalog, files)
    assert mapping.rows[0].status == "GAP" or all(r.source_path != dest.name for r in mapping.rows if r.status == "Present")
    assert mapping.flagged
