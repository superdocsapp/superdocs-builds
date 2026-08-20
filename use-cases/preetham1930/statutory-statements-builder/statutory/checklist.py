"""The disclosure checklist: 32 rows of data, and a grammar that evaluates them.

Nothing in this module contains an item id, a standard name or a trigger. The
checklist is found by its **columns**, never its filename, and every condition is
parsed from the CSV at run time. Adding a 33rd row is a data edit.

    condition    := "always" | account_test | event_name
    account_test := "account" code ("or" code)* "balance" [scope] operator number
    scope        := "current" | "prior"                      (default: current)
    operator     := ">" | ">=" | "<" | "<=" | "=" | "==" | "<>" | "!="

Three loud failures where the tempting default is a quiet one. An unparseable
condition, an unknown account code and an event with no detector each raise. A
silent `False` in any of them means "this disclosure is not required", which is
exactly the gap this app exists to close; a silent `True` invents work. Neither
is visible in the output, which is what makes stopping the right answer.

Several account codes joined by `or` are a **disjunction**: the item is required
if any one satisfies the comparison. A conjunctive reading would suppress the
lease maturity item whenever one of the current/non-current pair happened to be
nil - which is precisely the year it matters.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .csvspans import as_records, parse_csv
from .errors import UnknownAccountError, UnknownConditionError, UnknownEventError
from .figures import Cite

REQUIRED_COLUMNS = ("item_id", "requirement", "trigger_condition", "satisfied_by_note")

ACCOUNT_TEST = re.compile(
    r"^account\s+(?P<codes>\d+(?:\s+or\s+\d+)*)\s+balance"
    r"(?:\s+(?P<scope>current|prior))?\s*"
    r"(?P<op>>=|<=|<>|!=|==|=|>|<)\s*"
    r"(?P<number>-?\d+(?:\.\d+)?)\s*$",
    re.I,
)

OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "=": lambda a, b: a == b,
    "==": lambda a, b: a == b,
    "<>": lambda a, b: a != b,
    "!=": lambda a, b: a != b,
}

GRAMMAR = (
    'condition := "always" | account_test | event_name; '
    'account_test := "account" code ("or" code)* "balance" [current|prior] '
    "(>|>=|<|<=|=|==|<>|!=) number"
)


@dataclass(frozen=True)
class ChecklistItem:
    item_id: str
    standard: str
    requirement: str
    trigger: str
    prior_note: int | None  # the note number in *last year's* numbering
    severity: str
    row_cite: Cite

    @property
    def mapped_last_year(self) -> bool:
        return self.prior_note is not None


@dataclass(frozen=True)
class Trigger:
    """Why an item is required, with the citations that make it true."""

    item: ChecklistItem
    required: bool
    because: str
    cites: tuple[Cite, ...]


class Checklist:
    def __init__(self, path: Path, corpus_root: Path) -> None:
        self.path = path
        self.rel = path.relative_to(corpus_root).as_posix()
        header, records = as_records(parse_csv(path.read_bytes()))
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(
                f"{self.rel}: a disclosure checklist is recognised by its columns, not its "
                f"name. Missing: {', '.join(missing)}. Found: {', '.join(header)}"
            )
        self.items: list[ChecklistItem] = []
        for record in records:
            note_cell = record["satisfied_by_note"]
            self.items.append(
                ChecklistItem(
                    item_id=record["item_id"].text,
                    standard=record["standard"].text if "standard" in record else "",
                    requirement=record["requirement"].text,
                    trigger=record["trigger_condition"].text,
                    prior_note=int(note_cell.text) if note_cell.text else None,
                    severity=record["severity"].text if "severity" in record else "",
                    row_cite=Cite(
                        path=self.rel,
                        byte_start=record["requirement"].byte_start,
                        byte_end=record["requirement"].byte_end,
                        snippet=record["requirement"].value,
                        where=f"disclosure checklist, item {record['item_id'].text}",
                    ),
                )
            )

    def __len__(self) -> int:
        return len(self.items)

    def evaluate(self, ledger, events) -> list[Trigger]:
        return [self._evaluate_one(item, ledger, events) for item in self.items]

    def _evaluate_one(self, item: ChecklistItem, ledger, events) -> Trigger:
        condition = item.trigger.strip()
        if condition.lower() == "always":
            return Trigger(item, True, "required in every set of statements", ())

        match = ACCOUNT_TEST.match(condition)
        if match:
            return self._evaluate_accounts(item, match, ledger)

        if events.defines(condition):
            hits = events.hits(condition)
            if hits:
                return Trigger(
                    item,
                    True,
                    f"event '{condition}' detected in {hits[0].source}",
                    tuple(c for h in hits for c in h.cites),
                )
            return Trigger(item, False, f"event '{condition}' not detected in any source", ())

        raise UnknownConditionError(
            f"{self.rel}: item {item.item_id} has trigger {condition!r}, which is neither "
            f"'always', nor an account test, nor an event this build defines. "
            f"Grammar: {GRAMMAR}. Events defined: {', '.join(events.names()) or '(none)'}. "
            f"An unevaluable trigger is not 'not required' - it stops the run."
        )

    def _evaluate_accounts(self, item: ChecklistItem, match, ledger) -> Trigger:
        codes = re.split(r"\s+or\s+", match.group("codes"), flags=re.I)
        scope = (match.group("scope") or "current").lower()
        year = ledger.year if scope == "current" else ledger.prior_year
        operator = OPERATORS[match.group("op")]
        threshold = Decimal(match.group("number"))

        unknown = [c for c in codes if not ledger.has(c)]
        if unknown:
            raise UnknownAccountError(
                f"{self.rel}: item {item.item_id} tests account(s) {', '.join(unknown)}, which "
                f"the trial balance does not have. The ledger holds {len(ledger)} account(s): "
                f"{', '.join(ledger.codes())}. A missing account is not a nil balance."
            )

        cites: list[Cite] = []
        satisfied: list[str] = []
        for code in codes:
            account = ledger.account(code)
            cites.append(account.cite(year))
            if operator(account.balance(year), threshold):
                satisfied.append(code)
        if satisfied:
            detail = ", ".join(
                f"{c} ({ledger.account(c).name}) = {ledger.account(c).balance(year)}"
                for c in satisfied
            )
            return Trigger(item, True, f"{detail} in FY{year}", tuple(cites))
        return Trigger(item, False, f"no account in {', '.join(codes)} satisfies the test", ())


def check_unknown_event(name: str, events) -> None:
    """Kept separate so the error can be raised from a caller that knows the row."""
    if not events.defines(name):
        raise UnknownEventError(
            f"event {name!r} has no detector. Defined: {', '.join(events.names()) or '(none)'}"
        )
