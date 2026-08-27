"""The canonical fact ledger.

A `Fact` is an organisational fact (headcount, country count, an audited
figure, a certification date, ...) whose CURRENT value lives in exactly one
place: `fixtures/facts.yaml` (or whatever ledger YAML the caller points at).
`prior_values` records retired values — these are what makes a claim in a
proposal document STALE.

This module owns loading and validating that YAML. It does not read or
inspect any proposal document; that is the detection engine's job (T2).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterator, Union

import yaml

Number = Union[str, int, float]

ALLOWED_KINDS = {"integer", "decimal", "percentage", "currency", "year", "text"}


class FactLedgerError(Exception):
    """Base class for all fact-ledger validation errors."""


class DuplicateFactIdError(FactLedgerError):
    """Raised when two facts in the ledger share the same id."""


class InvalidFactKindError(FactLedgerError):
    """Raised when a fact's `kind` is not one of the allowed values."""


class InvalidDateError(FactLedgerError):
    """Raised when a date field is missing or cannot be parsed as a date."""


class StalePriorValueError(FactLedgerError):
    """Raised when a prior value is identical to the current value."""


class PriorValueDateOrderError(FactLedgerError):
    """Raised when a prior value's as_of is later than the fact's as_of."""


class EmptySubjectError(FactLedgerError):
    """Raised when a fact's subject is missing or empty."""


class EmptySynonymsError(FactLedgerError):
    """Raised when a fact's subject_synonyms list is missing or empty."""


class FactNotFoundError(FactLedgerError):
    """Raised when looking up a fact id that is not in the ledger."""


@dataclass(frozen=True)
class PriorValue:
    value: Number
    as_of: date
    retired_on: date


@dataclass(frozen=True)
class Fact:
    id: str  # stable slug, e.g. "headcount"
    subject: str  # canonical noun phrase, e.g. "permanent staff"
    subject_synonyms: list[str]  # alternate nouns the same fact is written as
    value: Number  # the CURRENT canonical value
    kind: str  # "integer" | "decimal" | "percentage" | "currency" | "year" | "text"
    unit: str | None  # e.g. "people", "countries", "USD", None
    source: str  # provenance, e.g. "HR headcount report (Workday export)"
    as_of: date  # when the canonical value became true
    prior_values: list[PriorValue]  # retired values


def _parse_date(raw_value: object, fact_id: str, field_name: str) -> date:
    """Validate that a YAML date field parsed to a real `date`.

    Dates in the ledger YAML are written as plain ISO `YYYY-MM-DD` scalars,
    which PyYAML parses natively into `datetime.date`. If the field is
    missing, or comes back as a `str` (e.g. because it was quoted, or is
    malformed and PyYAML fell back to a string), that is a data error.
    """
    if raw_value is None:
        raise InvalidDateError(
            f"fact '{fact_id}': {field_name} is missing — add an ISO date "
            f"(YYYY-MM-DD) for {field_name}"
        )
    if isinstance(raw_value, str):
        raise InvalidDateError(
            f"fact '{fact_id}': {field_name} value '{raw_value}' was parsed as "
            f"a string, not a date — write it as an unquoted ISO date "
            f"(YYYY-MM-DD) so PyYAML parses it natively"
        )
    if isinstance(raw_value, date):
        return raw_value
    raise InvalidDateError(
        f"fact '{fact_id}': {field_name} value {raw_value!r} could not be "
        f"parsed as a date — use an unquoted ISO date (YYYY-MM-DD)"
    )


def _build_fact(raw: dict) -> Fact:
    fact_id = raw.get("id")

    kind = raw.get("kind")
    if kind not in ALLOWED_KINDS:
        raise InvalidFactKindError(
            f"fact '{fact_id}': kind '{kind}' is not one of "
            f"{sorted(ALLOWED_KINDS)} — fix the 'kind' field in facts.yaml"
        )

    subject = raw.get("subject")
    if not subject:
        raise EmptySubjectError(
            f"fact '{fact_id}': subject is empty — add a canonical noun "
            f"phrase for this fact, e.g. 'permanent staff'"
        )

    subject_synonyms = raw.get("subject_synonyms")
    if not subject_synonyms:
        raise EmptySynonymsError(
            f"fact '{fact_id}': subject_synonyms is empty — add at least "
            f"one alternate phrasing of the subject in facts.yaml"
        )

    current_value = raw.get("value")
    as_of = _parse_date(raw.get("as_of"), fact_id, "as_of")

    prior_values: list[PriorValue] = []
    for pv_raw in raw.get("prior_values") or []:
        pv_value = pv_raw.get("value")
        pv_as_of = _parse_date(pv_raw.get("as_of"), fact_id, "prior_values.as_of")
        pv_retired_on = _parse_date(
            pv_raw.get("retired_on"), fact_id, "prior_values.retired_on"
        )

        if pv_value == current_value:
            raise StalePriorValueError(
                f"fact '{fact_id}': prior value {pv_value!r} equals the "
                f"current value — remove it from prior_values or correct "
                f"the current value"
            )
        if pv_as_of > as_of:
            raise PriorValueDateOrderError(
                f"fact '{fact_id}': prior value as_of {pv_as_of} is later "
                f"than the fact's as_of {as_of} — a prior value must "
                f"predate the current value's as_of"
            )

        prior_values.append(
            PriorValue(value=pv_value, as_of=pv_as_of, retired_on=pv_retired_on)
        )

    return Fact(
        id=fact_id,
        subject=subject,
        subject_synonyms=list(subject_synonyms),
        value=current_value,
        kind=kind,
        unit=raw.get("unit"),
        source=raw.get("source"),
        as_of=as_of,
        prior_values=prior_values,
    )


class FactLedger:
    """A validated collection of canonical `Fact`s, loaded from YAML."""

    def __init__(self, facts: list[Fact]):
        self._facts = facts
        self._by_id: dict[str, Fact] = {f.id: f for f in facts}

    @classmethod
    def load(cls, path: str | Path) -> "FactLedger":
        path = Path(path)
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        raw_facts = data.get("facts") or []
        facts: list[Fact] = []
        seen_ids: set[str] = set()
        for raw in raw_facts:
            fact_id = raw.get("id")
            if fact_id in seen_ids:
                raise DuplicateFactIdError(
                    f"fact '{fact_id}': duplicate fact id — each fact id "
                    f"must be unique; rename or remove the duplicate entry "
                    f"in facts.yaml"
                )
            seen_ids.add(fact_id)
            facts.append(_build_fact(raw))

        return cls(facts)

    @property
    def facts(self) -> list[Fact]:
        return list(self._facts)

    def get(self, fact_id: str) -> Fact:
        try:
            return self._by_id[fact_id]
        except KeyError:
            raise FactNotFoundError(
                f"fact '{fact_id}' not found in ledger — check the id "
                f"against facts.yaml"
            ) from None

    def stale_values(self, fact_id: str) -> list[PriorValue]:
        return list(self.get(fact_id).prior_values)

    def __iter__(self) -> Iterator[Fact]:
        return iter(self._facts)

    def __len__(self) -> int:
        return len(self._facts)
