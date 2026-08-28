from statistics import median

from .models import PriceRange, Property


# Use the closed price when available, otherwise the asking price
def comparable_price(comp: Property) -> int:
    price = comp.sale_price or comp.list_price
    if price <= 0:
        raise ValueError(f"Comparable {comp.address!r} has no usable price")
    return price


# Estimate value from the median comparable price per square foot
def estimate_price_range(subject: Property, comps: list[Property]) -> PriceRange:
    if subject.sqft <= 0:
        raise ValueError(
            "Subject property must have a positive square footage")
    if not comps:
        raise ValueError("At least one comparable property is required")

    price_per_sqft = [
        comparable_price(comp) / comp.sqft
        for comp in comps
        if comp.sqft > 0
    ]
    if not price_per_sqft:
        raise ValueError(
            "At least one comparable must have positive square footage")

    median_price_per_sqft = median(price_per_sqft)
    midpoint = round(subject.sqft * median_price_per_sqft)
    low = round(midpoint * 0.95 / 1000) * 1000
    high = round(midpoint * 1.05 / 1000) * 1000
    rationale = (
        f"Based on the median comparable price of "
        f"${median_price_per_sqft:,.0f} per square foot across "
        f"{len(price_per_sqft)} comparable(s), adjusted to the subject's "
        f"{subject.sqft:,} square feet."
    )
    return PriceRange(low=low, high=high, rationale=rationale)
