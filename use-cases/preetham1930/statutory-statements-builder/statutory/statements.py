"""The primary statements, rolled forward, with comparatives that are checked.

The reporting-year column comes from the ledger. The comparative column comes
from the ledger *and* from the signed prior-year set, and the two must agree to
the paisa. That double citation is what turns "the comparatives tie" from a
claim into a check: if the trial balance's prior-year column had drifted from
what was signed, this raises rather than printing a number that reconciles to
nothing.

Every subtotal and total is a `Derived` - computed on every read from the
account figures beneath it - so a statement cannot print a total that its own
rows do not support. The prior-year totals are then compared against the totals
the signed set actually prints, which is the second half of the same check.

The layout (which groups sit under which section header, and what the subtotal
is called) is configuration keyed on the ledger's own `group` column. A new
group is a data change plus one line here, not a rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .errors import ComparativeMismatchError, TieBreakError
from .figures import AnyFigure, Cite, Component, Derived, Figure
from .ledger import Account, TrialBalance
from .money import format_money, parse_money
from .priorset import PriorYearSet

# section header -> the ledger groups shown under it, then the section total.
BALANCE_SHEET_LAYOUT: tuple[tuple[str, tuple[str, ...], str | None], ...] = (
    ("ASSETS", ("Non-current assets", "Current assets"), "TOTAL ASSETS"),
    (
        "EQUITY AND LIABILITIES",
        ("Equity", "Non-current liabilities", "Current liabilities"),
        "TOTAL EQUITY AND LIABILITIES",
    ),
)
SUBTOTAL_CAPTION = {
    "Non-current assets": "Total non-current assets",
    "Current assets": "Total current assets",
    "Equity": "Total equity",
    "Non-current liabilities": "Total non-current liabilities",
    "Current liabilities": "Total current liabilities",
    "Income": "Total income",
    "Expenses": "Total expenses",
}
# Groups that get a printed sub-header row above them (Equity does not, in the
# signed set, and the roll-forward keeps the signed layout).
SUBHEADED = {
    "Non-current assets",
    "Current assets",
    "Non-current liabilities",
    "Current liabilities",
}

_ALIASES = (("wip", "work-in-progress"),)


def normalise_caption(text: str) -> str:
    lowered = " ".join(text.lower().split())
    for suffix in (" - non-current", " - current", " (net)"):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
    for short, long in _ALIASES:
        lowered = lowered.replace(f" and {short}", f" and {long}")
    return lowered.strip()


@dataclass
class Line:
    """One printed row. `kind` decides how it is typeset, not what it means."""

    caption: str
    kind: str  # section | subheader | account | subtotal | total | derivedline
    current: AnyFigure | None = None
    prior: AnyFigure | None = None
    account: Account | None = None
    prior_note_ref: int | None = None
    note_ref: int | None = None  # filled in once the note tree exists
    emphasis: bool = False

    @property
    def figures(self) -> tuple[AnyFigure, ...]:
        return tuple(f for f in (self.current, self.prior) if f is not None)


@dataclass
class Statement:
    key: str  # "balance_sheet" | "profit_and_loss"
    title: str  # without the date, which the renderer appends
    lines: list[Line] = field(default_factory=list)
    column_labels: tuple[str, str] = ("", "")

    def line(self, caption: str) -> Line | None:
        return next((line for line in self.lines if line.caption == caption), None)

    @property
    def figures(self) -> tuple[AnyFigure, ...]:
        return tuple(f for line in self.lines for f in line.figures)


@dataclass
class ComparativeCheck:
    caption: str
    ledger_value: Decimal
    signed_value: Decimal | None
    matched: bool
    reason: str


@dataclass
class RollForward:
    ledger: TrialBalance
    prior: PriorYearSet
    statements: list[Statement]
    comparative_checks: list[ComparativeCheck]
    ties: list[tuple[str, Decimal, Decimal, bool]]

    @property
    def year(self) -> int:
        return self.ledger.year

    @property
    def prior_year(self) -> int:
        return self.ledger.prior_year

    def statement(self, key: str) -> Statement:
        return next(s for s in self.statements if s.key == key)

    def figure_for(self, code: str, year: int) -> AnyFigure:
        line = next(
            line for line in self._all_lines() if line.account and line.account.code == code
        )
        return line.current if year == self.year else line.prior

    def caption_line(self, code: str) -> Line:
        return next(
            line for line in self._all_lines() if line.account and line.account.code == code
        )

    def total(self, caption: str) -> Derived:
        for line in self._all_lines():
            if line.caption == caption and isinstance(line.current, Derived):
                return line.current
        raise KeyError(caption)

    def prior_total(self, caption: str) -> Derived:
        for line in self._all_lines():
            if line.caption == caption and isinstance(line.prior, Derived):
                return line.prior
        raise KeyError(caption)

    def _all_lines(self) -> list[Line]:
        return [line for statement in self.statements for line in statement.lines]


class _ComparativeSource:
    """Locates a signed prior-year cell for a ledger account, once."""

    def __init__(self, prior: PriorYearSet) -> None:
        self._rows: dict[str, list] = {}
        for statement in prior.statements:
            for row in statement.rows:
                if row.is_section or row.is_total or not row.values:
                    continue
                self._rows.setdefault(normalise_caption(row.caption), []).append(row)

    def find(self, account: Account):
        candidates = self._rows.get(normalise_caption(account.name), [])
        if len(candidates) == 1:
            return candidates[0]
        for candidate in candidates:
            if normalise_caption(candidate.section) == normalise_caption(account.group):
                return candidate
        return None


def roll_forward(ledger: TrialBalance, prior: PriorYearSet, corpus_root: Path) -> RollForward:
    source = _ComparativeSource(prior)
    checks: list[ComparativeCheck] = []

    def figures_for(account: Account) -> tuple[Figure, Figure]:
        current = Figure(
            label=account.name,
            value=account.presented(ledger.year),
            basis="ledger",
            cites=(account.cite(ledger.year),),
        )
        prior_value = account.presented(ledger.prior_year)
        row = source.find(account)
        if row is None:
            if prior_value != 0:
                raise ComparativeMismatchError(
                    f"{account.code} ({account.name}) has a prior-year balance of "
                    f"{format_money(prior_value)} but no row in the signed prior-year set. "
                    f"A comparative that is not in the signed set cannot be presented as one; "
                    f"looked for caption {normalise_caption(account.name)!r} in "
                    f"{prior.rel}."
                )
            checks.append(
                ComparativeCheck(
                    account.name,
                    prior_value,
                    None,
                    True,
                    "new caption this year; nil in the ledger's prior-year column and absent "
                    "from the signed set - consistent",
                )
            )
            return current, Figure(
                label=f"{account.name} (comparative)",
                value=prior_value,
                basis="ledger",
                cites=(account.cite(ledger.prior_year),),
            )
        cell = row.values[0]
        cell_cite = row.cites[0]
        signed = parse_money(cell)
        if signed != prior_value:
            raise ComparativeMismatchError(
                f"comparative mismatch on {account.name!r}: the trial balance's "
                f"fy{ledger.prior_year} column presents {format_money(prior_value)} and the "
                f"signed prior-year set prints {cell} at {prior.rel} bytes "
                f"{cell_cite.byte_start}-{cell_cite.byte_end}. The comparatives must tie "
                f"exactly; neither side is preferred and this is a hard error."
            )
        checks.append(
            ComparativeCheck(account.name, prior_value, signed, True, "ledger and signed set agree")
        )
        return current, Figure(
            label=f"{account.name} (comparative)",
            value=prior_value,
            basis="comparative",
            cites=(account.cite(ledger.prior_year), cell_cite),
        )

    def note_ref_for(account: Account) -> int | None:
        row = source.find(account)
        return row.note_ref if row is not None else None

    balance_sheet = Statement("balance_sheet", "Balance Sheet as at")
    for section, groups, section_total in BALANCE_SHEET_LAYOUT:
        balance_sheet.lines.append(Line(section, "section", emphasis=True))
        section_components_current: list[Component] = []
        section_components_prior: list[Component] = []
        for group in groups:
            accounts = ledger.in_group("BS", group)
            if not accounts:
                continue
            if group in SUBHEADED:
                balance_sheet.lines.append(Line(group, "subheader"))
            group_current: list[Component] = []
            group_prior: list[Component] = []
            for account in accounts:
                current, prior_figure = figures_for(account)
                balance_sheet.lines.append(
                    Line(
                        caption=account.name,
                        kind="account",
                        current=current,
                        prior=prior_figure,
                        account=account,
                        prior_note_ref=note_ref_for(account),
                    )
                )
                group_current.append(Component(current))
                group_prior.append(Component(prior_figure))
            caption = SUBTOTAL_CAPTION[group]
            balance_sheet.lines.append(
                Line(
                    caption,
                    "subtotal",
                    Derived(caption, tuple(group_current)),
                    Derived(f"{caption} (comparative)", tuple(group_prior)),
                    emphasis=True,
                )
            )
            section_components_current.extend(group_current)
            section_components_prior.extend(group_prior)
        if section_total:
            balance_sheet.lines.append(
                Line(
                    section_total,
                    "total",
                    Derived(section_total, tuple(section_components_current)),
                    Derived(f"{section_total} (comparative)", tuple(section_components_prior)),
                    emphasis=True,
                )
            )

    profit_and_loss = Statement(
        "profit_and_loss", "Statement of Profit and Loss for the year ended"
    )
    pl_totals: dict[str, tuple[Derived, Derived]] = {}
    for group in ("Income", "Expenses", "Tax expense"):
        accounts = ledger.in_group("PL", group)
        if not accounts:
            continue
        current_components: list[Component] = []
        prior_components: list[Component] = []
        for account in accounts:
            current, prior_figure = figures_for(account)
            profit_and_loss.lines.append(
                Line(
                    caption=account.name,
                    kind="account",
                    current=current,
                    prior=prior_figure,
                    account=account,
                    prior_note_ref=note_ref_for(account),
                )
            )
            current_components.append(Component(current))
            prior_components.append(Component(prior_figure))
        if group in SUBTOTAL_CAPTION:
            caption = SUBTOTAL_CAPTION[group]
            current_total = Derived(caption, tuple(current_components))
            prior_total = Derived(f"{caption} (comparative)", tuple(prior_components))
            profit_and_loss.lines.append(
                Line(caption, "subtotal", current_total, prior_total, emphasis=True)
            )
            pl_totals[group] = (current_total, prior_total)
        else:
            pl_totals[group] = (
                Derived(f"Total {group.lower()}", tuple(current_components)),
                Derived(f"Total {group.lower()} (comparative)", tuple(prior_components)),
            )
        if group == "Expenses":
            pbt_current = Derived(
                "Profit before tax",
                (Component(pl_totals["Income"][0]), Component(current_total, -1)),
            )
            pbt_prior = Derived(
                "Profit before tax (comparative)",
                (Component(pl_totals["Income"][1]), Component(prior_total, -1)),
            )
            profit_and_loss.lines.insert(
                len(profit_and_loss.lines),
                Line("Profit before tax", "derivedline", pbt_current, pbt_prior, emphasis=True),
            )
            pl_totals["PBT"] = (pbt_current, pbt_prior)
    tax_current, tax_prior = pl_totals["Tax expense"]
    profit_and_loss.lines.append(
        Line(
            "Profit for the year",
            "derivedline",
            Derived(
                "Profit for the year",
                (Component(pl_totals["PBT"][0]), Component(tax_current, -1)),
            ),
            Derived(
                "Profit for the year (comparative)",
                (Component(pl_totals["PBT"][1]), Component(tax_prior, -1)),
            ),
            emphasis=True,
        )
    )

    rolled = RollForward(ledger, prior, [balance_sheet, profit_and_loss], checks, [])
    _check_ties(rolled, prior)
    return rolled


def _check_ties(rolled: RollForward, prior: PriorYearSet) -> None:
    """The four ties in TASK.md section 2, plus every prior-year total the signed set prints."""
    ties = rolled.ties
    for year_label, getter in (
        (rolled.year, lambda c: rolled.total(c)),
        (rolled.prior_year, lambda c: rolled.prior_total(c)),
    ):
        assets = getter("TOTAL ASSETS").value
        equity_and_liabilities = getter("TOTAL EQUITY AND LIABILITIES").value
        ok = assets == equity_and_liabilities
        ties.append(
            (
                f"FY{year_label} total assets = total equity and liabilities",
                assets,
                equity_and_liabilities,
                ok,
            )
        )
        if not ok:
            raise TieBreakError(
                f"FY{year_label} balance sheet does not balance: total assets "
                f"{format_money(assets)} against total equity and liabilities "
                f"{format_money(equity_and_liabilities)}, a difference of "
                f"{format_money(assets - equity_and_liabilities)}."
            )

    # Every total the signed set prints must equal the total our comparatives
    # derive. This is the half of "the comparatives tie" that a caption-by-caption
    # check cannot see: a set can agree row by row and still print a wrong total.
    for statement in prior.statements:
        for row in statement.rows:
            if not row.values:
                continue
            try:
                ours = rolled.prior_total(row.caption)
            except KeyError:
                continue
            signed = parse_money(row.values[0])
            ok = ours.value == signed
            ties.append(
                (f"FY{rolled.prior_year} {row.caption} vs signed set", ours.value, signed, ok)
            )
            if not ok:
                raise ComparativeMismatchError(
                    f"comparative total mismatch on {row.caption!r}: our roll-forward derives "
                    f"{format_money(ours.value)} from {len(ours.components)} ledger row(s), the "
                    f"signed prior-year set prints {row.values[0]}. Working: {ours.workings()}"
                )

    other_equity = rolled.caption_line("2110")
    profit = rolled.statement("profit_and_loss").line("Profit for the year").current
    opening = other_equity.prior.value
    closing = other_equity.current.value
    ok = opening + profit.value == closing
    ties.append((f"{other_equity.caption} rolls forward", opening + profit.value, closing, ok))
    if not ok:
        raise TieBreakError(
            f"{other_equity.caption} does not roll forward: {format_money(opening)} + "
            f"{format_money(profit.value)} = {format_money(opening + profit.value)}, but the "
            f"ledger closes at {format_money(closing)}. The difference "
            f"{format_money(closing - opening - profit.value)} is undistributed and unexplained."
        )


def unused_cite(cite: Cite) -> Cite:  # pragma: no cover - keeps the import honest
    return cite
