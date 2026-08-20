"""The intake is the only channel by which a power reaches the document.

Every refusal here is a refusal to draft. That is the point: a power of attorney
with a quietly missing limitation, or a quietly dropped power, or a party with
no name, reads perfectly well and is wrong in a way nobody notices.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from poa.errors import (
    IncompleteIntakeError,
    UnknownJurisdictionError,
    UnknownPoaTypeError,
    UnknownPowerError,
)
from poa.intake import load_intake, validate


def _write(tmp_path: Path, base: Path, **overrides) -> Path:
    raw = json.loads(base.read_text(encoding="utf-8"))
    raw.update(overrides)
    path = tmp_path / "intake.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_the_three_shipped_intakes_load(library, intakes: Path) -> None:
    for name in ("durable-financial", "healthcare", "limited-real-property"):
        intake = load_intake(intakes / f"{name}.json", library)
        assert intake.intake_id == name
        assert intake.successor_agent.name, "the successor-agent clause is never optional"


def test_an_unknown_power_id_is_a_hard_error(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        intakes / "durable-financial.json",
        granted_powers=["fin-banking", "fin-crypto-yolo"],
    )
    with pytest.raises(UnknownPowerError) as exc:
        load_intake(path, library)
    message = str(exc.value)
    assert "fin-crypto-yolo" in message
    assert "config/powers.csv" in message
    assert "never dropped" in message, "an unknown power must not be silently ignored"


def test_an_unknown_poa_type_is_never_approximated(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(tmp_path, intakes / "durable-financial.json", poa_type="springing")
    with pytest.raises(UnknownPoaTypeError, match="general/limited/durable"):
        load_intake(path, library)


def test_an_unknown_jurisdiction_names_the_csv_to_edit(
    library, intakes: Path, tmp_path: Path
) -> None:
    path = _write(tmp_path, intakes / "durable-financial.json", jurisdiction="atlantis")
    with pytest.raises(UnknownJurisdictionError, match=r"config/jurisdictions\.csv"):
        load_intake(path, library)


def test_a_limited_poa_with_no_limitation_is_refused(
    library, intakes: Path, tmp_path: Path
) -> None:
    """The single most consequential thing this build could get wrong."""
    path = _write(tmp_path, intakes / "limited-real-property.json", limitation=None)
    with pytest.raises(IncompleteIntakeError) as exc:
        load_intake(path, library)
    assert "requires_limitation=yes" in str(exc.value)
    assert "general one wearing the wrong heading" in str(exc.value)


def test_a_limitation_on_a_type_that_cannot_carry_one_is_refused(
    library, intakes: Path, tmp_path: Path
) -> None:
    """The other direction: a limit that would be silently dropped."""
    path = _write(
        tmp_path, intakes / "durable-financial.json", limitation="only the Hyderabad account"
    )
    with pytest.raises(IncompleteIntakeError, match="silently dropped"):
        load_intake(path, library)


def test_a_missing_party_is_refused_and_named(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(tmp_path, intakes / "durable-financial.json", successor_agent=None)
    with pytest.raises(IncompleteIntakeError) as exc:
        load_intake(path, library)
    assert "successor_agent" in str(exc.value)
    assert "not optional" in str(exc.value)


def test_a_party_with_no_address_is_refused(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(
        tmp_path, intakes / "durable-financial.json", agent={"name": "A Person", "address": ""}
    )
    with pytest.raises(IncompleteIntakeError, match="agent"):
        load_intake(path, library)


def test_granting_nothing_is_refused(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(tmp_path, intakes / "durable-financial.json", granted_powers=[])
    with pytest.raises(IncompleteIntakeError, match="not a shorter document"):
        load_intake(path, library)


def test_a_power_granted_twice_is_refused(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(
        tmp_path, intakes / "durable-financial.json", granted_powers=["fin-banking", "fin-banking"]
    )
    with pytest.raises(IncompleteIntakeError, match="more than once"):
        load_intake(path, library)


def test_real_property_powers_need_a_described_property(
    library, intakes: Path, tmp_path: Path
) -> None:
    path = _write(tmp_path, intakes / "limited-real-property.json", real_property_description=None)
    with pytest.raises(IncompleteIntakeError, match="unbounded"):
        load_intake(path, library)


def test_no_commencement_is_refused(library, intakes: Path, tmp_path: Path) -> None:
    path = _write(tmp_path, intakes / "durable-financial.json", effective_date="")
    with pytest.raises(IncompleteIntakeError, match="a question, not a draft"):
        load_intake(path, library)


def test_validation_runs_on_an_object_too_not_only_on_a_file(library, intakes: Path) -> None:
    """There is one validator, and both routes into the assembler go through it."""
    intake = load_intake(intakes / "durable-financial.json", library)
    validate(intake, library)
    with pytest.raises(UnknownPowerError):
        validate(replace(intake, granted_powers=("not-a-power",)), library)


def test_categories_come_from_the_catalogue_not_from_the_order_typed(
    library, intakes: Path, tmp_path: Path
) -> None:
    """Two intakes granting the same powers must produce the same document."""
    forwards = load_intake(intakes / "limited-real-property.json", library)
    backwards = replace(forwards, granted_powers=tuple(reversed(forwards.granted_powers)))
    assert forwards.categories(library) == backwards.categories(library)
    for category in forwards.categories(library):
        assert forwards.powers_in(library, category) == backwards.powers_in(library, category)
