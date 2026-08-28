import pytest

from cma.models import Property
from cma.pricing import estimate_price_range


def make_property(*, sqft: int, sale_price: int | None = None) -> Property:
    return Property(
        address="123 Test Street",
        city="Austin",
        state="TX",
        beds=3,
        baths=2.0,
        sqft=sqft,
        lot_size_sqft=7000,
        year_built=2018,
        list_price=sale_price or 0,
        sale_price=sale_price,
        sale_date="2026-01-01" if sale_price else None,
        photo_url="https://example.com/photo.jpg",
    )


def test_estimate_uses_median_price_per_square_foot() -> None:
    subject = make_property(sqft=2000)
    comps = [
        make_property(sqft=1800, sale_price=540000),
        make_property(sqft=2200, sale_price=660000),
        make_property(sqft=2000, sale_price=620000),
    ]

    result = estimate_price_range(subject, comps)

    assert result.low == 570000
    assert result.high == 630000
    assert "median comparable price" in result.rationale


def test_estimate_handles_wildly_different_comparable_sizes() -> None:
    subject = make_property(sqft=2000)
    comps = [
        make_property(sqft=500, sale_price=150000),
        make_property(sqft=1900, sale_price=570000),
        make_property(sqft=2100, sale_price=630000),
        make_property(sqft=6000, sale_price=1800000),
    ]

    result = estimate_price_range(subject, comps)

    assert result.low == 570000
    assert result.high == 630000


def test_estimate_rejects_missing_comparables() -> None:
    with pytest.raises(ValueError, match="At least one comparable"):
        estimate_price_range(make_property(sqft=2000), [])
