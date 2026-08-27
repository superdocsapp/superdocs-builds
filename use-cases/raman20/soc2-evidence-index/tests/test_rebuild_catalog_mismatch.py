import pytest

from soc2_index.catalog import load_catalog
from soc2_index.pipeline import UsageError, materialize
from tests.conftest import FIXTURES, build_from


def test_rebuild_catalog_mismatch(sample_catalog):
    v1, _, _ = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    full = load_catalog()
    # force full catalog path against sample from_index
    from soc2_index.paths import default_catalog_path

    with pytest.raises(UsageError):
        materialize(
            FIXTURES / "cedar-harbor-v2",
            default_catalog_path(),
            sample=False,
            org="Cedar Harbor Labs",
            period="2025",
            generated_at="1970-01-01T00:00:00Z",
            from_index=v1,
        )
