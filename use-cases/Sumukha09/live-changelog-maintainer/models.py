from dataclasses import dataclass, field
from typing import List

@dataclass
class Release:
    version: str
    date: str
    added: List[str] = field(default_factory=list)
    improved: List[str] = field(default_factory=list)
    fixed: List[str] = field(default_factory=list)
    breaking_changes: List[str] = field(default_factory=list)

@dataclass
class Changelog:
    title: str = "Product Changelog"
    releases: List[Release] = field(default_factory=list)
