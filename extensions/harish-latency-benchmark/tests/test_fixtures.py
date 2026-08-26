from bench.fixtures import make_synthetic_doc, doc_bytes, SIZE_TIERS


def test_all_tiers_generate_nonempty_content():
    for tier in SIZE_TIERS:
        doc = make_synthetic_doc(tier)
        assert len(doc) > 0
        assert "Section" in doc


def test_tier_sizes_roughly_ordered():
    small = len(make_synthetic_doc("small").split())
    medium = len(make_synthetic_doc("medium").split())
    large = len(make_synthetic_doc("large").split())
    assert small < medium < large


def test_doc_bytes_is_utf8_encodable():
    b = doc_bytes("small")
    assert isinstance(b, bytes)
    assert b.decode("utf-8")


def test_unknown_tier_raises():
    import pytest
    with pytest.raises(ValueError):
        make_synthetic_doc("huge")
