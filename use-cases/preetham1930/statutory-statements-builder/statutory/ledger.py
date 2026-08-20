"""The trial balance: the ledger every primary-statement caption is drawn from.

The reporting year is the highest `fy<year>` column present and the comparative
year is the next highest, so no year is written down in this module and a
FY2027 corpus needs a new column, not a code change (hard rule 6).

Signs are the ledger's own. Liabilities, equity and income are carried negative,
and no absolute value is ever taken - `balance > 0` has to keep meaning "debit
balance" or the trigger grammar is lying about what it evaluates (Assumption 20,
carried over as a principle and re-checked here against all 32 conditions).

Presentation sign is a property of the caption's *group*, not of the account: a
statutory balance sheet shows liabilities positive. The map below is the whole
of that rule and it is configuration, not logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from .csvspans import as_records, parse_csv
from .figures import Cite
from .money import parse_money

FY_COLUMN = re.compile(r"^fy(?P<year>\d{4})_")

# presented = balance * factor, keyed on the ledger's own `group` column.
PRESENTATION_SIGN: dict[str, int] = {
    "Non-current assets": 1,
    "Current assets": 1,
    "Equity": -1,
    "Non-current liabilities": -1,
    "Current liabilities": -1,
    "Income": -1,
    "Expenses": 1,
    "Tax expense": 1,
}


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    statement: str  # BS | PL
    group: str
    balances: dict[int, Decimal]  # year -> signed balance
    cites: dict[int, Cite]  # year -> citation of that cell
    name_cite: Cite
    order: int  # position in the file; the statutory presentation order

    def balance(self, year: int) -> Decimal:
        return self.balances[year]

    def presented(self, year: int) -> Decimal:
        return self.balances[year] * PRESENTATION_SIGN[self.group]

    def cite(self, year: int) -> Cite:
        return self.cites[year]


class TrialBalance:
    def __init__(self, path: Path, corpus_root: Path) -> None:
        self.path = path
        self.rel = path.relative_to(corpus_root).as_posix()
        raw = path.read_bytes()
        header, records = as_records(parse_csv(raw))
        years: list[int] = []
        for column in header:
            match = FY_COLUMN.match(column)
            if match:
                years.append(int(match.group("year")))
        if len(years) < 2:
            raise ValueError(
                f"{self.rel}: a roll-forward needs a reporting year and a comparative; "
                f"found fy columns for {years or 'nothing'}"
            )
        self.years = sorted(years, reverse=True)
        self.year = self.years[0]
        self.prior_year = self.years[1]
        self._columns = {y: next(c for c in header if c.startswith(f"fy{y}_")) for y in self.years}

        self.accounts: list[Account] = []
        for order, record in enumerate(records):
            balances: dict[int, Decimal] = {}
            cites: dict[int, Cite] = {}
            for year in self.years:
                cell = record[self._columns[year]]
                balances[year] = parse_money(cell.text)
                cites[year] = Cite(
                    path=self.rel,
                    byte_start=cell.byte_start,
                    byte_end=cell.byte_end,
                    snippet=cell.value,
                    where=(
                        f"trial balance, account {record['account_code'].text}, "
                        f"column {self._columns[year]}"
                    ),
                )
            name_cell = record["account_name"]
            group = record["group"].text
            if group not in PRESENTATION_SIGN:
                raise ValueError(
                    f"{self.rel}: account {record['account_code'].text} is in group {group!r}, "
                    f"which has no presentation sign. Known groups: "
                    f"{', '.join(sorted(PRESENTATION_SIGN))}"
                )
            self.accounts.append(
                Account(
                    code=record["account_code"].text,
                    name=name_cell.text,
                    statement=record["statement"].text,
                    group=group,
                    balances=balances,
                    cites=cites,
                    name_cite=Cite(
                        path=self.rel,
                        byte_start=name_cell.byte_start,
                        byte_end=name_cell.byte_end,
                        snippet=name_cell.value,
                        where=f"trial balance, account {record['account_code'].text}, name",
                    ),
                    order=order,
                )
            )
        self._by_code = {a.code: a for a in self.accounts}

    def __len__(self) -> int:
        return len(self.accounts)

    def has(self, code: str) -> bool:
        return code in self._by_code

    def account(self, code: str) -> Account:
        return self._by_code[code]

    def codes(self) -> list[str]:
        return [a.code for a in self.accounts]

    def in_group(self, statement: str, group: str) -> list[Account]:
        return [a for a in self.accounts if a.statement == statement and a.group == group]

    def groups(self, statement: str) -> list[str]:
        seen: list[str] = []
        for account in self.accounts:
            if account.statement == statement and account.group not in seen:
                seen.append(account.group)
        return seen

    def year_label(self, year: int) -> str:
        return f"31 March {year}"
