"""The library is data. These tests are what make that sentence checkable.

Two of them are the load-bearing ones:

- `test_no_clause_text_is_hardcoded_anywhere_in_the_package` greps this
  package's own `.py` files for every clause body, power label, power sentence,
  notice, type label and jurisdiction name in `config/`. A hit means the library
  stopped being the library.
- `test_adding_a_jurisdiction_is_a_data_edit` adds a row to a copy of the config
  and requires the behaviour to change with zero code edits.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from poa.assemble import assemble
from poa.errors import LibraryRefusedError, UnknownConditionError, UnresolvedPlaceholderError
from poa.intake import load_intake
from poa.library import Library

PACKAGE = Path(__file__).resolve().parent.parent / "poa"


def _copy_config(config: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "config"
    shutil.copytree(config, destination)
    return destination


def test_no_clause_text_is_hardcoded_anywhere_in_the_package(library) -> None:
    sources = {path: path.read_text(encoding="utf-8-sig") for path in PACKAGE.rglob("*.py")}
    strings: list[tuple[str, str]] = []
    for clause in library.clauses:
        strings.append(("clause body", clause.body))
        if clause.heading:
            strings.append(("clause heading", clause.heading))
    for power in library.powers.values():
        strings.append(("power label", power.label))
        strings.append(("power language", power.language))
    for poa_type in library.types.values():
        strings.append(("type label", poa_type.label))
        strings.append(("durability language", poa_type.durability_language))
    for jurisdiction in library.jurisdictions.values():
        strings.append(("jurisdiction", jurisdiction.label))
        strings.append(("governing law", jurisdiction.governing_law))
    for notice in library.notices.values():
        strings.append(("notice", notice.text))
    for blank in library.blank_form.values():
        strings.append(("blank-form marker", blank))

    hits = [
        f"{path.name}: {kind} {value[:60]!r}"
        for kind, value in strings
        if len(value) > 12
        for path, text in sources.items()
        if value in text
    ]
    assert not hits, (
        "the clause library has leaked into code:\n  "
        + "\n  ".join(hits)
        + "\nAdding a jurisdiction or a power type must be a data edit "
        "(builds/poa-generator/INVARIANTS.md D1)."
    )


def test_the_hardcoding_check_is_not_vacuous(library) -> None:
    """A guard that passes because it found nothing to check is decoration."""
    assert len(library.clauses) >= 15
    assert len(library.powers) >= 12
    assert len(library.notices) == 2
    text = (PACKAGE / "assemble.py").read_text(encoding="utf-8")
    assert "power.language" in text, "the check greps for values the code really does emit"


def test_adding_a_jurisdiction_is_a_data_edit(config: Path, intakes: Path, tmp_path: Path) -> None:
    """Zero code edits. One row."""
    root = _copy_config(config, tmp_path)
    before = Library(root)
    assert "in-ka" not in before.jurisdictions

    path = root / "jurisdictions.csv"
    defer = "must be confirmed with qualified counsel before anything is signed."
    path.write_text(
        path.read_text(encoding="utf-8")
        + f'in-ka,"Karnataka, India","Karnataka law is intended to govern this instrument; '
        f'whether that choice is effective is a question for qualified counsel.",'
        f'"The witnesses required {defer}","Whether notarisation is required {defer}"\n',
        encoding="utf-8",
    )
    after = Library(root)
    assert "in-ka" in after.jurisdictions

    intake_path = tmp_path / "ka.json"
    raw = (intakes / "durable-financial.json").read_text(encoding="utf-8")
    intake_path.write_text(raw.replace('"in-ts"', '"in-ka"'), encoding="utf-8")
    draft = assemble(load_intake(intake_path, after), after)
    assert "Karnataka, India" in draft.html("target")
    assert "Karnataka, India" in draft.html("skeleton"), "jurisdiction is structure, not an edit"


def test_adding_a_power_is_a_data_edit(config: Path, intakes: Path, tmp_path: Path) -> None:
    root = _copy_config(config, tmp_path)
    path = root / "powers.csv"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "fin-safedeposit,financial,Safe deposit,The Agent may open and close a safe deposit "
        "locker held in the name of the Principal.\n",
        encoding="utf-8",
    )
    updated = Library(root)
    intake_path = tmp_path / "extra.json"
    raw = (intakes / "durable-financial.json").read_text(encoding="utf-8")
    intake_path.write_text(raw.replace('"fin-banking"', '"fin-safedeposit"'), encoding="utf-8")
    draft = assemble(load_intake(intake_path, updated), updated)
    assert "safe deposit locker" in draft.html("target")


def test_a_jurisdiction_row_that_asserts_a_requirement_is_refused(
    config: Path, tmp_path: Path
) -> None:
    """INVARIANTS.md A4. We are not qualified to say what a jurisdiction requires."""
    root = _copy_config(config, tmp_path)
    path = root / "jurisdictions.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "The number and eligibility of witnesses required for this instrument must be "
            "confirmed with qualified counsel before anything is signed.",
            "Two witnesses are required.",
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(LibraryRefusedError) as exc:
        Library(root)
    assert "witness_requirement" in str(exc.value)
    assert "not qualified" in str(exc.value)
    assert "deferral-markers.txt" in str(exc.value)


def test_an_empty_deferral_marker_list_is_refused(config: Path, tmp_path: Path) -> None:
    """An empty guard list is a guard that cannot be satisfied, not one switched off."""
    root = _copy_config(config, tmp_path)
    (root / "deferral-markers.txt").write_text("# nothing\n", encoding="utf-8")
    with pytest.raises(LibraryRefusedError, match="cannot be satisfied"):
        Library(root)


def test_an_unparseable_condition_is_a_hard_error(config: Path, tmp_path: Path) -> None:
    """A silent False would drop a clause out of a power of attorney."""
    root = _copy_config(config, tmp_path)
    path = root / "clause-library.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "successor,100,successor,Successor agent,p,body,always,",
            "successor,100,successor,Successor agent,p,body,if the moon is right,",
            1,
        ),
        encoding="utf-8",
    )
    updated = Library(root)
    with pytest.raises(UnknownConditionError) as exc:
        updated.select("durable", ("financial",))
    assert "if the moon is right" in str(exc.value)
    assert "no symptom" in str(exc.value)


def test_an_unresolved_placeholder_is_a_hard_error(
    config: Path, intakes: Path, tmp_path: Path
) -> None:
    root = _copy_config(config, tmp_path)
    path = root / "clause-library.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "The Principal appoints {agent_name}",
            "The Principal appoints {agent_middle_name} {agent_name}",
            1,
        ),
        encoding="utf-8",
    )
    updated = Library(root)
    with pytest.raises(UnresolvedPlaceholderError) as exc:
        assemble(load_intake(intakes / "durable-financial.json", updated), updated)
    assert "agent_middle_name" in str(exc.value)
    assert "never emptied" in str(exc.value)


def test_a_csv_row_with_an_unquoted_comma_is_refused_not_truncated(
    config: Path, tmp_path: Path
) -> None:
    root = _copy_config(config, tmp_path)
    path = root / "powers.csv"
    path.write_text(
        path.read_text(encoding="utf-8")
        + "fin-oops,financial,Careless,The Agent may do this, and that, and the other.\n",
        encoding="utf-8",
    )
    with pytest.raises(LibraryRefusedError) as exc:
        Library(root)
    assert "more fields than the header" in str(exc.value)
    assert "cut in half" in str(exc.value)


def test_a_duplicate_clause_id_is_refused(config: Path, tmp_path: Path) -> None:
    root = _copy_config(config, tmp_path)
    path = root / "clause-library.csv"
    path.write_text(
        path.read_text(encoding="utf-8") + "successor,999,closing,Duplicate,p,body,always,x\n",
        encoding="utf-8",
    )
    with pytest.raises(LibraryRefusedError, match="more than once"):
        Library(root)


def test_a_clause_reference_the_library_cannot_resolve_is_refused(
    config: Path, tmp_path: Path
) -> None:
    root = _copy_config(config, tmp_path)
    path = root / "clause-library.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "{clause_ref:successor}", "{clause_ref:no-such-clause}", 1
        ),
        encoding="utf-8",
    )
    with pytest.raises(LibraryRefusedError, match="no-such-clause"):
        Library(root)


def test_a_signature_table_with_no_blank_column_is_refused(config: Path, tmp_path: Path) -> None:
    """INVARIANTS.md A3: there is always somewhere left to sign, and it is empty."""
    root = _copy_config(config, tmp_path)
    path = root / "signature-table.csv"
    path.write_text(
        path.read_text(encoding="utf-8").replace(",blank", ",label"),
        encoding="utf-8",
    )
    with pytest.raises(LibraryRefusedError, match="never implies"):
        Library(root)
