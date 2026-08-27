from soc2_index.pipeline import materialize
from tests.conftest import FIXTURES


def test_materialize_sample():
    index, files, diff, mapping = materialize(
        FIXTURES / "cedar-harbor-v1",
        None,
        sample=True,
        org="Cedar Harbor Labs",
        period="2025-01-01/2025-12-31",
        generated_at="1970-01-01T00:00:00Z",
    )
    assert index.catalog_id == "tsc-cc6-cc7"
    assert diff is None
    assert len(index.rows) == 13
    assert mapping.ambiguous == []
