"""Tests for freshness_auditor.ledger.

Loads the real fixture ledger and asserts its shape, then drives every
named validation error with a small inline YAML fixture per case.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from freshness_auditor.ledger import (
    DuplicateFactIdError,
    EmptySubjectError,
    EmptySynonymsError,
    Fact,
    FactLedger,
    FactNotFoundError,
    InvalidDateError,
    InvalidFactKindError,
    PriorValue,
    PriorValueDateOrderError,
    StalePriorValueError,
)

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"
FACTS_PATH = FIXTURES_DIR / "facts.yaml"


def write_ledger(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "facts.yaml"
    path.write_text(body, encoding="utf-8")
    return path


# --- real fixture ledger ----------------------------------------------------


def test_loads_four_facts():
    ledger = FactLedger.load(FACTS_PATH)
    ids = {f.id for f in ledger.facts}
    assert ids == {"headcount", "country_count", "beneficiaries_2025", "iso_9001_renewal"}
    assert len(ledger) == 4


def test_headcount_fact_shape():
    ledger = FactLedger.load(FACTS_PATH)
    fact = ledger.get("headcount")
    assert isinstance(fact, Fact)
    assert fact.subject == "permanent staff"
    assert fact.subject_synonyms  # non-empty
    assert fact.value == 1450
    assert fact.kind == "integer"
    assert fact.unit == "people"
    assert fact.source == "HR headcount report (Workday export)"
    assert fact.as_of == date(2026, 1, 15)
    assert len(fact.prior_values) == 1
    prior = fact.prior_values[0]
    assert isinstance(prior, PriorValue)
    assert prior.value == 1200
    assert prior.as_of == date(2023, 6, 1)
    assert prior.retired_on == date(2026, 1, 15)


def test_iso_9001_renewal_is_text_kind_with_string_value():
    ledger = FactLedger.load(FACTS_PATH)
    fact = ledger.get("iso_9001_renewal")
    assert fact.kind == "text"
    assert fact.value == "March 2026"
    assert fact.unit is None
    assert fact.prior_values[0].value == "March 2023"


def test_all_four_facts_have_exactly_one_prior_value():
    ledger = FactLedger.load(FACTS_PATH)
    for fact in ledger:
        assert len(fact.prior_values) == 1, fact.id


def test_get_unknown_fact_raises_named_error():
    ledger = FactLedger.load(FACTS_PATH)
    with pytest.raises(FactNotFoundError):
        ledger.get("does_not_exist")


def test_stale_values_returns_prior_values_for_fact():
    ledger = FactLedger.load(FACTS_PATH)
    stale = ledger.stale_values("country_count")
    assert stale == [PriorValue(value=14, as_of=date(2023, 9, 1), retired_on=date(2026, 2, 1))]


def test_iter_yields_all_facts():
    ledger = FactLedger.load(FACTS_PATH)
    assert {f.id for f in ledger} == {f.id for f in ledger.facts}


# --- validation errors -------------------------------------------------


def test_duplicate_fact_id_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values: []
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 200
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values: []
""",
    )
    with pytest.raises(DuplicateFactIdError):
        FactLedger.load(path)


def test_invalid_kind_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: not_a_real_kind
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values: []
""",
    )
    with pytest.raises(InvalidFactKindError):
        FactLedger.load(path)


def test_missing_as_of_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    prior_values: []
""",
    )
    with pytest.raises(InvalidDateError):
        FactLedger.load(path)


def test_unparseable_as_of_raises_when_quoted_string(tmp_path):
    # Quoting the date forces PyYAML to hand back a str instead of a date.
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: "not a date"
    prior_values: []
""",
    )
    with pytest.raises(InvalidDateError):
        FactLedger.load(path)


def test_prior_value_equals_current_value_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values:
      - value: 100
        as_of: 2023-01-01
        retired_on: 2026-01-01
""",
    )
    with pytest.raises(StalePriorValueError):
        FactLedger.load(path)


def test_prior_value_as_of_after_current_as_of_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values:
      - value: 50
        as_of: 2026-06-01
        retired_on: 2026-06-01
""",
    )
    with pytest.raises(PriorValueDateOrderError):
        FactLedger.load(path)


def test_empty_subject_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: ""
    subject_synonyms: [staff]
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values: []
""",
    )
    with pytest.raises(EmptySubjectError):
        FactLedger.load(path)


def test_empty_subject_synonyms_raises(tmp_path):
    path = write_ledger(
        tmp_path,
        """
facts:
  - id: headcount
    subject: permanent staff
    subject_synonyms: []
    value: 100
    kind: integer
    unit: people
    source: test
    as_of: 2026-01-01
    prior_values: []
""",
    )
    with pytest.raises(EmptySynonymsError):
        FactLedger.load(path)
