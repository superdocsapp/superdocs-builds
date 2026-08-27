"""Core domain types.

The whole system rests on one idea: a *fact* is a number that was computed from
the spreadsheet, carries the cells it came from, and knows how to print itself.
Prose never contains a number, it contains a reference to a fact. Everything
else in this package exists to keep that true.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

Unit = Literal["currency", "percent", "number", "text", "date"]

# How a fact renders. Kept as a small closed set so a template author can't
# invent a format the verifier doesn't know how to reproduce.
FormatSpec = Literal[
    "currency0",  # $1,234
    "currency2",  # $1,234.56
    "number0",  # 1,234
    "number1",  # 1,234.5
    "number2",  # 1,234.56
    "percent0",  # 12%
    "percent1",  # 12.3%
    "signed_percent1",  # +12.3% / -4.0%
    "signed_currency0",  # +$1,234 / -$98
    "multiple1",  # 1.4x
    "text",  # verbatim
]


@dataclass(frozen=True, slots=True)
class Fact:
    """One value the report is allowed to state.

    ``provenance`` is not decoration: it is the audit trail that lets a reader
    (and the tests) walk from a sentence back to the cells that justify it.
    """

    key: str
    value: Decimal | str
    unit: Unit
    label: str
    provenance: str
    fmt: FormatSpec = "number0"

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("fact key must be non-empty")
        if self.unit == "text" and not isinstance(self.value, str):
            raise TypeError(f"fact {self.key!r} is text but value is {type(self.value).__name__}")
        if self.unit != "text" and not isinstance(self.value, Decimal):
            raise TypeError(
                f"fact {self.key!r} is numeric and must hold a Decimal, got "
                f"{type(self.value).__name__}, floats silently lose cents"
            )

    @property
    def token(self) -> str:
        """The placeholder the language model is allowed to emit."""
        return "{{fact:" + self.key + "}}"

    def digest(self) -> str:
        """Stable hash over everything that could change the rendered text.

        Provenance is deliberately excluded: moving a column changes where a
        number came from but not what the sentence says, and we do not want a
        column insert to invalidate every section of the report.
        """
        payload = json.dumps(
            {"key": self.key, "value": str(self.value), "unit": self.unit, "fmt": self.fmt},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]


class FactSet(Mapping[str, Fact]):
    """An immutable, key-addressed collection of facts."""

    __slots__ = ("_facts",)

    def __init__(self, facts: list[Fact] | dict[str, Fact] | None = None) -> None:
        items = facts.values() if isinstance(facts, dict) else (facts or [])
        table: dict[str, Fact] = {}
        for fact in items:
            if fact.key in table:
                raise ValueError(f"duplicate fact key {fact.key!r}")
            table[fact.key] = fact
        self._facts = table

    def __getitem__(self, key: str) -> Fact:
        return self._facts[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)

    def digests(self) -> dict[str, str]:
        return {key: fact.digest() for key, fact in self._facts.items()}

    def with_facts(self, extra: list[Fact]) -> FactSet:
        return FactSet(list(self._facts.values()) + extra)


@dataclass(slots=True)
class Section:
    """One addressable block of the report.

    ``fact_keys`` is what makes incremental re-runs possible: it records which
    facts this section's prose actually depends on, so a data change can be
    resolved to the specific sections it invalidates.
    """

    id: str
    heading: str
    template: str  # prose containing {{fact:...}} tokens, never literal numbers
    fact_keys: tuple[str, ...] = ()
    chunk_id: str | None = None  # SuperDocs data-chunk-id, learned after first upload
    rendered: str | None = None  # last rendered HTML, used for byte-identity checks

    def body_digest(self) -> str:
        """Hash of the token-level prose, before substitution."""
        return hashlib.sha256(self.template.encode()).hexdigest()[:16]


@dataclass(slots=True)
class ReportManifest:
    """Everything needed to re-run a report incrementally.

    Persisted after every successful run. On the next run we diff the incoming
    facts against ``fact_digests`` to decide what, if anything, to touch.
    """

    report_id: str
    session_id: str
    source_range: str
    sections: list[Section] = field(default_factory=list)
    fact_digests: dict[str, str] = field(default_factory=dict)
    revision: int = 0
    template_id: str | None = None
    chart_url: str | None = None
    chart_digest: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "report_id": self.report_id,
                "session_id": self.session_id,
                "source_range": self.source_range,
                "revision": self.revision,
                "template_id": self.template_id,
                "chart_url": self.chart_url,
                "chart_digest": self.chart_digest,
                "fact_digests": self.fact_digests,
                "sections": [
                    {
                        "id": s.id,
                        "heading": s.heading,
                        "template": s.template,
                        "fact_keys": list(s.fact_keys),
                        "chunk_id": s.chunk_id,
                        "rendered": s.rendered,
                    }
                    for s in self.sections
                ],
            },
            indent=2,
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, blob: str) -> ReportManifest:
        raw = json.loads(blob)
        return cls(
            report_id=raw["report_id"],
            session_id=raw["session_id"],
            source_range=raw["source_range"],
            revision=raw.get("revision", 0),
            template_id=raw.get("template_id"),
            chart_url=raw.get("chart_url"),
            chart_digest=raw.get("chart_digest"),
            fact_digests=raw.get("fact_digests", {}),
            sections=[
                Section(
                    id=s["id"],
                    heading=s["heading"],
                    template=s["template"],
                    fact_keys=tuple(s.get("fact_keys", ())),
                    chunk_id=s.get("chunk_id"),
                    rendered=s.get("rendered"),
                )
                for s in raw.get("sections", [])
            ],
        )
