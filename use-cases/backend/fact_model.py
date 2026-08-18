from dataclasses import dataclass
from typing import List


@dataclass
class GameInfo:
    title: str
    studio: str
    genre: str
    release_date: str
    platforms: List[str]
    price: str
    availability: str


@dataclass
class Quote:
    text: str
    attribution: str


@dataclass
class Asset:
    filename: str
    type: str
    caption: str
    credit: str


@dataclass
class Award:
    name: str
    year: int


@dataclass
class Coverage:
    publication: str
    headline: str
    url: str


@dataclass
class GameFacts:
    game: GameInfo
    core_description: str
    features: List[str]
    history: str
    inspiration: str
    quote: Quote
    awards: List[Award]
    coverage: List[Coverage]
    assets: List[Asset]