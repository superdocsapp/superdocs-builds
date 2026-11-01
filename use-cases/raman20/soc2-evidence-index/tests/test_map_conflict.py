from soc2_index.ingest import walk
from soc2_index.map import apply
from tests.conftest import FIXTURES


def test_conflict_ambiguous(sample_catalog):
    files = walk(FIXTURES / "mapper/conflict")
    mapping = apply(sample_catalog, files)
    assert len(mapping.ambiguous) == 1
    assert mapping.ambiguous[0].relative_path.endswith("PHYS-RBAC-MIX.md")
    assert not any(
        r.status == "Present" and r.source_path and "PHYS-RBAC" in r.source_path for r in mapping.rows
    )
