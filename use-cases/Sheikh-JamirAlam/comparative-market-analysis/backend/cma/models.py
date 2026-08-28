"""Data shapes used by the CMA pipeline"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Property:
    address: str
    city: str
    state: str
    beds: int
    baths: float
    sqft: int
    lot_size_sqft: int
    year_built: int
    list_price: int
    sale_price: int | None
    sale_date: str | None
    photo_url: str
    distance_miles: float | None = None
    days_on_market: int | None = None


@dataclass(frozen=True)
class PriceRange:
    low: int
    high: int
    rationale: str


@dataclass(frozen=True)
class Branding:
    agent_name: str
    brokerage: str
    phone: str
    email: str
    logo_url: str | None = None
    primary_color: str = "#1F4E5F"
    accent_color: str = "#D6A756"
