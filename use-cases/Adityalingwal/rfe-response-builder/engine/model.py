from dataclasses import dataclass, field
from enum import Enum


class Coverage(str, Enum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    NOT_PROVIDED = "not_provided"


@dataclass(frozen=True)
class Request:
    id: str
    title: str
    text: str


@dataclass(frozen=True)
class SourceSection:
    file: str
    heading: str
    text: str


@dataclass(frozen=True)
class Match:
    request_id: str
    file: str
    heading: str
    excerpt: str
    score: float
    shared_stems: int = 0


@dataclass
class ChecklistRow:
    request_id: str
    title: str
    coverage: Coverage
    matches: list[Match] = field(default_factory=list)
    reason: str = ""
