"""The clause library, and it is data.

Hard constraint of this build: adding a jurisdiction or a power type is a **data
edit**. So every clause, every power, every POA type, every jurisdiction, both
notices, the forbidden-phrase list and the signature block's rows live in
`config/*.csv`, and there is a test that greps this package's own `.py` files
and fails if any of that text appears as a string literal.

Two loud failures where the tempting default is a quiet one, both copied as an
argument from `system/`'s Decision 17 and rebuilt here:

- an **unparseable clause condition** raises. A silent `False` would drop a
  clause out of a power of attorney, and a missing clause has no symptom - the
  document reads perfectly well without it.
- an **unresolved placeholder** raises. It is never left in the text and never
  emptied. `of  , born` is a document that went out wrong quietly.

The condition grammar is small on purpose:

    condition := "always"
               | "type is" <type_id>
               | "type in" <type_id>[|<type_id>...]
               | "category granted" <category>
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .errors import LibraryRefusedError, UnknownConditionError

GRAMMAR = "always | type is <type_id> | type in <type_id>|<type_id> | category granted <category>"
PLACEHOLDER = re.compile(r"\{([a-z_]+)(?::([a-z_-]+))?\}")


@dataclass(frozen=True)
class Clause:
    clause_id: str
    sort_order: int
    section: str
    heading: str
    tag: str
    style_role: str
    applies_when: str
    body: str

    @property
    def numbered(self) -> bool:
        return bool(self.heading)


@dataclass(frozen=True)
class Power:
    power_id: str
    category: str
    label: str
    language: str


@dataclass(frozen=True)
class PoaType:
    type_id: str
    label: str
    requires_limitation: bool
    durability_language: str


@dataclass(frozen=True)
class Jurisdiction:
    jurisdiction_id: str
    label: str
    governing_law: str
    witness_requirement: str
    notarisation_requirement: str


@dataclass(frozen=True)
class Notice:
    notice_id: str
    label: str
    text: str


@dataclass(frozen=True)
class ForbiddenPhrase:
    phrase: str
    why: str


@dataclass(frozen=True)
class SignatureRow:
    role_key: str
    role_label: str
    name_placeholder: str


@dataclass(frozen=True)
class SignatureColumn:
    column_key: str
    column_label: str
    fill: str  # label | placeholder | blank

    @property
    def blank(self) -> bool:
        return self.fill == "blank"


class Library:
    """Everything the draft is made of, loaded from `config/`."""

    def __init__(self, config_root: Path) -> None:
        self.root = config_root
        self.clauses = _clauses(config_root / "clause-library.csv")
        self.powers = _powers(config_root / "powers.csv")
        self.types = _types(config_root / "poa-types.csv")
        self.notices = _notices(config_root / "notices.csv")
        self.forbidden = _forbidden(config_root / "forbidden-phrases.csv")
        self.signature_rows = _signature_rows(config_root / "signature-rows.csv")
        self.signature_columns = _signature_columns(config_root / "signature-table.csv")
        self.blank_form = _blank_form(config_root / "blank-form.csv")
        self.deferral_markers = _markers(config_root / "deferral-markers.txt")
        self.jurisdictions = _jurisdictions(
            config_root / "jurisdictions.csv", self.deferral_markers
        )
        self.power_order = tuple(self.powers)
        seen: list[str] = []
        for power in self.powers.values():
            if power.category not in seen:
                seen.append(power.category)
        self.category_order = tuple(seen)
        self._assert_clause_ids_resolve()

    # -- selection ---------------------------------------------------------

    def applies(self, clause: Clause, poa_type: str, categories: tuple[str, ...]) -> bool:
        """Evaluate a clause condition. Never returns False because it did not
        understand - that is what the raise is for."""
        condition = clause.applies_when.strip()
        if condition == "always":
            return True
        if condition.startswith("type is "):
            return poa_type == condition[len("type is ") :].strip()
        if condition.startswith("type in "):
            allowed = [t.strip() for t in condition[len("type in ") :].split("|")]
            return poa_type in allowed
        if condition.startswith("category granted "):
            return condition[len("category granted ") :].strip() in categories
        raise UnknownConditionError(
            f"clause {clause.clause_id!r} in {self.root / 'clause-library.csv'} has condition "
            f"{condition!r}, which this grammar cannot parse. The grammar is: {GRAMMAR}. "
            f"An unparseable condition is never read as 'this clause does not apply': a clause "
            f"silently dropped out of a power of attorney has no symptom in the finished "
            f"document."
        )

    def select(self, poa_type: str, categories: tuple[str, ...]) -> list[Clause]:
        return [c for c in self.clauses if self.applies(c, poa_type, categories)]

    # -- integrity ---------------------------------------------------------

    def _assert_clause_ids_resolve(self) -> None:
        known = {c.clause_id for c in self.clauses}
        for clause in self.clauses:
            for name, argument in PLACEHOLDER.findall(clause.body):
                if name == "clause_ref" and argument not in known:
                    raise LibraryRefusedError(
                        f"clause {clause.clause_id!r} refers to clause {argument!r}, which the "
                        f"library does not define. A cross-reference that cannot resolve in the "
                        f"library can never resolve in a draft."
                    )
                if name == "notice" and argument not in self.notices:
                    raise LibraryRefusedError(
                        f"clause {clause.clause_id!r} refers to notice {argument!r}; the library "
                        f"defines {sorted(self.notices)}."
                    )
                if name == "powers" and argument not in self.category_order:
                    raise LibraryRefusedError(
                        f"clause {clause.clause_id!r} refers to power category {argument!r}; the "
                        f"catalogue defines {list(self.category_order)}."
                    )


# -- loaders ---------------------------------------------------------------


def _rows(path: Path) -> list[dict[str, str]]:
    """Read a config CSV, refusing any row that does not match the header.

    `csv.DictReader` is quietly forgiving: a row with more fields than the
    header puts the surplus in a `None` key, and a row with fewer leaves `None`
    values. Both are how an unquoted comma inside a clause turns into a document
    that is missing half a sentence and says nothing about it. Neither is
    tolerated here - this is the library the whole draft is made of.
    """
    out: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for number, row in enumerate(reader, start=2):
            surplus = row.pop(None, None)
            if surplus:
                raise LibraryRefusedError(
                    f"{path} line {number} has more fields than the header "
                    f"{reader.fieldnames}. The surplus is {surplus}, which almost always means "
                    f"a comma inside an unquoted field - and a clause silently cut in half is "
                    f"a document that goes out wrong quietly."
                )
            missing = sorted(k for k, v in row.items() if v is None)
            if missing:
                raise LibraryRefusedError(
                    f"{path} line {number} has no value for {missing}. An empty column is "
                    f"written as an empty field, never omitted."
                )
            out.append({k: v.strip() for k, v in row.items()})
    return out


def _clauses(path: Path) -> tuple[Clause, ...]:
    clauses = [
        Clause(
            clause_id=row["clause_id"],
            sort_order=int(row["sort_order"]),
            section=row["section"],
            heading=row["heading"],
            tag=row["tag"],
            style_role=row["style_role"],
            applies_when=row["applies_when"],
            body=row["body"],
        )
        for row in _rows(path)
    ]
    ids = [c.clause_id for c in clauses]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if duplicated:
        raise LibraryRefusedError(
            f"{path} defines {duplicated} more than once. A clause id is how a cross-reference "
            f"finds its target, so a duplicate makes a reference ambiguous."
        )
    orders = [c.sort_order for c in clauses]
    if len(set(orders)) != len(orders):
        raise LibraryRefusedError(
            f"{path} has two clauses at the same sort_order, so the clause order - and therefore "
            f"the clause numbering - depends on how the file happened to be read."
        )
    return tuple(sorted(clauses, key=lambda c: c.sort_order))


def _powers(path: Path) -> dict[str, Power]:
    out: dict[str, Power] = {}
    for row in _rows(path):
        if row["power_id"] in out:
            raise LibraryRefusedError(f"{path} defines power {row['power_id']!r} twice")
        out[row["power_id"]] = Power(
            power_id=row["power_id"],
            category=row["category"],
            label=row["label"],
            language=row["language"],
        )
    return out


def _types(path: Path) -> dict[str, PoaType]:
    out: dict[str, PoaType] = {}
    for row in _rows(path):
        requires = row["requires_limitation"].lower()
        if requires not in ("yes", "no"):
            raise LibraryRefusedError(
                f"{path}: type {row['type_id']!r} has requires_limitation={requires!r}; "
                f"the column takes 'yes' or 'no' and nothing else, because a value this loader "
                f"guessed at would decide whether a limited POA can be drafted with no limit."
            )
        out[row["type_id"]] = PoaType(
            type_id=row["type_id"],
            label=row["label"],
            requires_limitation=requires == "yes",
            durability_language=row["durability_language"],
        )
    return out


def _jurisdictions(path: Path, markers: tuple[str, ...]) -> dict[str, Jurisdiction]:
    out: dict[str, Jurisdiction] = {}
    for row in _rows(path):
        for column in ("witness_requirement", "notarisation_requirement"):
            text = row[column].lower()
            if not any(marker in text for marker in markers):
                raise LibraryRefusedError(
                    f"{path}: jurisdiction {row['jurisdiction_id']!r} states {column} as fact:\n"
                    f"  {row[column]}\n"
                    f"This build is not qualified to say what a jurisdiction requires "
                    f"(INVARIANTS.md A4), so the text must defer - it must contain one of "
                    f"{list(markers)}, from config/deferral-markers.txt. The row is refused at "
                    f"load time rather than softened at render time, because a softened "
                    f"assertion still reaches the reader."
                )
        out[row["jurisdiction_id"]] = Jurisdiction(
            jurisdiction_id=row["jurisdiction_id"],
            label=row["label"],
            governing_law=row["governing_law"],
            witness_requirement=row["witness_requirement"],
            notarisation_requirement=row["notarisation_requirement"],
        )
    return out


def _notices(path: Path) -> dict[str, Notice]:
    out: dict[str, Notice] = {}
    for row in _rows(path):
        if not row["text"]:
            raise LibraryRefusedError(f"{path}: notice {row['notice_id']!r} has empty text")
        out[row["notice_id"]] = Notice(
            notice_id=row["notice_id"], label=row["label"], text=row["text"]
        )
    return out


def _forbidden(path: Path) -> tuple[ForbiddenPhrase, ...]:
    return tuple(
        ForbiddenPhrase(phrase=row["phrase"].lower(), why=row["why"]) for row in _rows(path)
    )


def _signature_rows(path: Path) -> tuple[SignatureRow, ...]:
    return tuple(
        SignatureRow(
            role_key=row["role_key"],
            role_label=row["role_label"],
            name_placeholder=row["name_placeholder"],
        )
        for row in _rows(path)
    )


def _signature_columns(path: Path) -> tuple[SignatureColumn, ...]:
    columns = tuple(
        SignatureColumn(
            column_key=row["column_key"], column_label=row["column_label"], fill=row["fill"]
        )
        for row in _rows(path)
    )
    allowed = {"label", "placeholder", "blank"}
    unknown = sorted({c.fill for c in columns} - allowed)
    if unknown:
        raise LibraryRefusedError(
            f"{path} uses fill {unknown}; the column takes {sorted(allowed)}. A fill this loader "
            f"guessed at would decide whether a signature cell is emitted empty."
        )
    if not any(c.blank for c in columns):
        raise LibraryRefusedError(
            f"{path} marks no column blank, so the signature block would be emitted with "
            f"nothing left to sign. INVARIANTS.md A3: this product never implies that signing "
            f"happened."
        )
    return columns


def _blank_form(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for row in _rows(path):
        if not row["blank_text"]:
            raise LibraryRefusedError(
                f"{path}: placeholder {row['placeholder']!r} has empty blank text. A blank form "
                f"whose gaps are invisible reads as a finished document."
            )
        out[row["placeholder"]] = row["blank_text"]
    return out


def _markers(path: Path) -> tuple[str, ...]:
    lines = [
        line.strip().lower()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not lines:
        raise LibraryRefusedError(
            f"{path} lists no deferral markers, so every jurisdiction row would be refused. "
            f"An empty guard list is a guard that cannot be satisfied, not one that is switched "
            f"off."
        )
    return tuple(lines)
