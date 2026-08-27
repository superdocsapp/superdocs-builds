"""Turn a selected spreadsheet range into facts.

Nothing in this module calls a model. Every number the report will ever state
is computed here, in code, from the cells, which is what makes "the numbers in
the prose match the sheet exactly" a property of the design rather than a hope.

The shape we expect is the one finance actually selects: a header row of
periods, a left column of line items, numbers in between. Anything that does
not fit that shape is reported as a parse failure, never guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, DivisionByZero, InvalidOperation

from .models import Fact, FactSet
from .sanitize import sanitise_label

# Trailing/leading currency symbols and separators we strip before parsing.
_CURRENCY_CHARS = "$€£¥₹"
_NUMERIC_RE = re.compile(r"^-?[\d,]*\.?\d+$")


class RangeParseError(ValueError):
    """The selection is not a shape this build can read."""


def column_letter(index: int) -> str:
    """0-based column index to A1 letters (0 -> A, 26 -> AA)."""
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def parse_cell(raw: str) -> tuple[Decimal | None, str | None]:
    """Parse one cell into (value, unit-hint).

    Returns ``(None, None)`` for anything that is not a number, blanks, labels,
    error values. Accepts the notations a finance sheet actually contains:
    ``$1,234``, ``(980)`` for negatives, ``12.5%``, ``1 234``.
    """
    if raw is None:
        return None, None
    text = str(raw).strip()
    if not text:
        return None, None

    unit: str | None = None
    negative = False

    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()

    for symbol in _CURRENCY_CHARS:
        if symbol in text:
            unit = "currency"
            text = text.replace(symbol, "")

    text = text.replace(" ", "").replace(" ", "").strip()

    if text.endswith("%"):
        unit = "percent"
        text = text[:-1].strip()

    if not text or not _NUMERIC_RE.match(text):
        return None, None

    try:
        value = Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None, None

    return (-value if negative else value), unit


def _slug(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    return slug or "item"


@dataclass(slots=True)
class Series:
    """One line item across the selected periods.

    ``label`` is always the sanitised form, it is what reaches prompts, facts
    and documents. ``raw_label`` keeps what the cell actually said so a flagged
    row can be shown to the human verbatim.
    """

    label: str
    slug: str
    values: list[Decimal | None]
    unit: str
    row_a1: str
    raw_label: str = ""
    flagged: bool = False
    stated_total: Decimal | None = None  # the sheet's own total, if it had one
    sheet_row: int = 0  # absolute row, so A1 can be rebuilt if columns change

    @property
    def present(self) -> list[Decimal]:
        return [v for v in self.values if v is not None]

    @property
    def latest(self) -> Decimal | None:
        for value in reversed(self.values):
            if value is not None:
                return value
        return None

    @property
    def previous(self) -> Decimal | None:
        seen = 0
        for value in reversed(self.values):
            if value is not None:
                seen += 1
                if seen == 2:
                    return value
        return None


@dataclass(slots=True)
class Table:
    """A parsed selection: periods across the top, series down the side."""

    sheet: str
    a1: str
    periods: list[str]
    series: list[Series]
    origin_row: int
    origin_col: int
    flagged_periods: tuple[str, ...] = ()
    total_label: str | None = None  # header of a trailing totals column, if any
    total_conflicts: list[str] = field(default_factory=list)


def read_table(values: list[list[str]], sheet: str, a1: str) -> Table:
    """Parse a raw 2-D range into a :class:`Table`.

    The header row and label column are required. Demanding them is a deliberate
    choice: inferring them from a ragged selection is where this class of tool
    usually starts quietly producing wrong reports.
    """
    grid = [row for row in values if any(str(c).strip() for c in row)]
    if len(grid) < 2:
        raise RangeParseError("selection needs a header row and at least one data row")

    origin_row, origin_col = _parse_origin(a1)

    header = grid[0]
    if len(header) < 2:
        raise RangeParseError("selection needs a label column and at least one period column")

    # Sanitise at the boundary: everything downstream, facts, prompts, the
    # document skeleton, consumes the safe form and never sees the raw cell.
    header_labels = [sanitise_label(c) for c in header[1:]]
    periods = [h.safe for h in header_labels]
    flagged_periods = [h for h in header_labels if h.flagged]
    if not any(periods):
        raise RangeParseError("header row has no period labels")

    series: list[Series] = []
    for offset, row in enumerate(grid[1:], start=1):
        raw = str(row[0]).strip() if row else ""
        if not raw:
            continue
        checked = sanitise_label(raw)
        label = checked.safe
        cells = list(row[1:]) + [""] * (len(periods) - len(row[1:]))
        parsed = [parse_cell(c) for c in cells[: len(periods)]]
        vals = [v for v, _ in parsed]
        if not any(v is not None for v in vals):
            continue  # a spacer or a text-only row, not a data series

        hints = {u for _, u in parsed if u}
        unit = "currency" if "currency" in hints else ("percent" if "percent" in hints else "number")

        sheet_row = origin_row + offset
        row_a1 = (
            f"{sheet}!{column_letter(origin_col + 1)}{sheet_row}"
            f":{column_letter(origin_col + len(periods))}{sheet_row}"
        )
        series.append(
            Series(
                label=label,
                slug=_slug(label),
                values=vals,
                unit=unit,
                row_a1=row_a1,
                raw_label=checked.original,
                flagged=checked.flagged,
                sheet_row=sheet_row,
            )
        )

    if not series:
        raise RangeParseError("no numeric rows found in the selection")

    table = Table(sheet, a1, periods, series, origin_row, origin_col)
    table.flagged_periods = tuple(h.original for h in flagged_periods)
    _split_off_totals_column(table)
    return table


_TOTAL_HEADER_RE = re.compile(
    r"\b(total|totals|ytd|fy|sum|cumulative|full[\s-]?year|year[\s-]?to[\s-]?date)\b",
    re.IGNORECASE,
)


def _looks_like_total(table: Table) -> bool:
    """Is the final column a total rather than another period?

    Finance selections routinely end in a totals column, and treating one as a
    period is not a cosmetic problem: it makes "the latest period" the total and
    turns every period-over-period figure into nonsense. Detected two ways,
    because either alone misses real sheets, a column headed "FY24" with no
    other clue, and a column headed "Total" that is actually an average.
    """
    if len(table.periods) < 3:
        return False  # too few columns to tell a total from a period

    if _TOTAL_HEADER_RE.search(table.periods[-1]):
        return True

    agreeing = comparable = 0
    for s in table.series:
        body = s.values[:-1]
        stated = s.values[-1]
        present = [v for v in body if v is not None]
        if stated is None or len(present) < 2:
            continue
        comparable += 1
        total = sum(present, start=Decimal(0))
        if total == 0:
            continue
        if abs(stated - total) <= abs(total) * Decimal("0.005"):
            agreeing += 1

    return comparable >= 2 and agreeing / comparable >= Decimal("0.6")


def _close(a: Decimal, b: Decimal, tolerance: str = "0.005") -> bool:
    if b == 0:
        return a == 0
    return abs(a - b) <= abs(b) * Decimal(tolerance)


def _split_off_totals_column(table: Table) -> None:
    """Move a trailing totals column out of the period axis.

    The stated totals are kept rather than discarded: where the sheet's own
    total disagrees with its periods, that is a real finding for the reviewer,
    not something to quietly paper over.

    Not every totals cell is a sum. For a stock measure, headcount, a balance,
    a retention rate, the column holds the closing value, and summing four
    quarters of headcount is meaningless. Both readings are accepted, and only a
    figure that matches neither is reported as a conflict.
    """
    if not _looks_like_total(table):
        return

    table.total_label = table.periods[-1]
    table.periods = table.periods[:-1]

    for s in table.series:
        s.stated_total = s.values[-1]
        s.values = s.values[:-1]
        # The provenance range must shrink with the data it describes.
        s.row_a1 = (
            f"{table.sheet}!{column_letter(table.origin_col + 1)}{s.sheet_row}"
            f":{column_letter(table.origin_col + len(table.periods))}{s.sheet_row}"
        )

        present = [v for v in s.values if v is not None]
        if s.stated_total is None or not present:
            continue

        computed = sum(present, start=Decimal(0))
        closing = present[-1]
        if _close(s.stated_total, computed) or _close(s.stated_total, closing):
            continue  # reads as either a sum or a closing balance; both are fine

        table.total_conflicts.append(
            f"{s.label}: the sheet states a {table.total_label} of {s.stated_total:,} but the "
            f"periods sum to {computed:,} and close at {closing:,} ({s.row_a1})"
        )


def _parse_origin(a1: str) -> tuple[int, int]:
    """Top-left row/column of an A1 range like ``B2:M14``."""
    start = a1.split("!")[-1].split(":")[0]
    match = re.match(r"^([A-Za-z]+)(\d+)$", start.strip())
    if not match:
        return 1, 0
    letters, digits = match.groups()
    col = 0
    for ch in letters.upper():
        col = col * 26 + (ord(ch) - 64)
    return int(digits), col - 1


def _fmt_for(unit: str, signed: bool = False) -> str:
    if unit == "currency":
        return "signed_currency0" if signed else "currency0"
    if unit == "percent":
        return "signed_percent1" if signed else "percent1"
    return "number0"


def derive_facts(table: Table) -> FactSet:
    """Compute every fact the narrative is permitted to reference."""
    facts: list[Fact] = [
        Fact(
            key="period.first",
            value=table.periods[0],
            unit="text",
            label="First period in the selection",
            provenance=f"{table.sheet}!{table.a1} header",
            fmt="text",
        ),
        Fact(
            key="period.last",
            value=table.periods[-1],
            unit="text",
            label="Latest period in the selection",
            provenance=f"{table.sheet}!{table.a1} header",
            fmt="text",
        ),
        Fact(
            key="period.count",
            value=Decimal(len(table.periods)),
            unit="number",
            label="Number of periods",
            provenance=f"{table.sheet}!{table.a1} header",
        ),
        Fact(
            key="table.series_count",
            value=Decimal(len(table.series)),
            unit="number",
            label="Number of line items",
            provenance=f"{table.sheet}!{table.a1}",
        ),
    ]

    latest_total = sum(
        (s.latest for s in table.series if s.latest is not None), start=Decimal(0)
    )

    for s in table.series:
        prefix = f"series.{s.slug}"
        facts.append(
            Fact(
                key=f"{prefix}.name",
                value=s.label,
                unit="text",
                label=f"Name of line item “{s.label}”",
                provenance=s.row_a1,
                fmt="text",
            )
        )

        if s.present:
            facts += [
                Fact(
                    key=f"{prefix}.total",
                    value=sum(s.present, start=Decimal(0)),
                    unit=s.unit,
                    label=f"{s.label}: total across all periods",
                    provenance=f"SUM({s.row_a1})",
                    fmt=_fmt_for(s.unit),
                ),
                Fact(
                    key=f"{prefix}.peak",
                    value=max(s.present),
                    unit=s.unit,
                    label=f"{s.label}: highest period value",
                    provenance=f"MAX({s.row_a1})",
                    fmt=_fmt_for(s.unit),
                ),
                Fact(
                    key=f"{prefix}.trough",
                    value=min(s.present),
                    unit=s.unit,
                    label=f"{s.label}: lowest period value",
                    provenance=f"MIN({s.row_a1})",
                    fmt=_fmt_for(s.unit),
                ),
                Fact(
                    key=f"{prefix}.mean",
                    value=sum(s.present, start=Decimal(0)) / Decimal(len(s.present)),
                    unit=s.unit,
                    label=f"{s.label}: mean period value",
                    provenance=f"AVERAGE({s.row_a1})",
                    fmt=_fmt_for(s.unit),
                ),
            ]
            # Peak and trough are offered as a pair. An earlier run had only
            # peak_period, and the model duly invented trough_period; the
            # validator caught it, but a foreseeable gap is better closed than
            # policed.
            for name, chosen in (("peak", max(s.present)), ("trough", min(s.present))):
                facts.append(
                    Fact(
                        key=f"{prefix}.{name}_period",
                        value=table.periods[s.values.index(chosen)],
                        unit="text",
                        label=f"{s.label}: period of the {'highest' if name == 'peak' else 'lowest'} value",
                        provenance=s.row_a1,
                        fmt="text",
                    )
                )

        if s.latest is not None:
            facts.append(
                Fact(
                    key=f"{prefix}.latest",
                    value=s.latest,
                    unit=s.unit,
                    label=f"{s.label} in {table.periods[-1]}",
                    provenance=s.row_a1,
                    fmt=_fmt_for(s.unit),
                )
            )
            if latest_total and s.unit == "currency":
                facts.append(
                    Fact(
                        key=f"{prefix}.share_latest",
                        value=(s.latest / latest_total) * Decimal(100),
                        unit="percent",
                        label=f"{s.label} as a share of the latest-period total",
                        provenance=f"{s.row_a1} ÷ total of latest column",
                        fmt="percent1",
                    )
                )

        prev = s.previous
        if s.latest is not None and prev is not None:
            delta = s.latest - prev
            facts.append(
                Fact(
                    key=f"{prefix}.delta_abs",
                    value=delta,
                    unit=s.unit,
                    label=f"{s.label}: change vs the prior period",
                    provenance=f"{s.row_a1} last minus previous",
                    fmt=_fmt_for(s.unit, signed=True),
                )
            )
            pct = _safe_pct(delta, prev)
            if pct is not None:
                facts.append(
                    Fact(
                        key=f"{prefix}.delta_pct",
                        value=pct,
                        unit="percent",
                        label=f"{s.label}: percent change vs the prior period",
                        provenance=f"{s.row_a1} period-over-period",
                        fmt="signed_percent1",
                    )
                )
            facts.append(
                Fact(
                    key=f"{prefix}.direction",
                    value="increased" if delta > 0 else ("decreased" if delta < 0 else "held flat"),
                    unit="text",
                    label=f"{s.label}: direction of travel",
                    provenance=f"sign of {s.row_a1} period-over-period",
                    fmt="text",
                )
            )
            if pct is not None:
                facts.append(
                    Fact(
                        key=f"{prefix}.magnitude",
                        value=magnitude_band(pct),
                        unit="text",
                        label=(
                            f"{s.label}: size of the move as an adverb, reads as "
                            f"“<direction> <magnitude>”, e.g. “increased sharply”"
                        ),
                        provenance=f"band of {s.row_a1} period-over-period change",
                        fmt="text",
                    )
                )

        streak = describe_streak(s.present)
        if streak:
            facts.append(
                Fact(
                    key=f"{prefix}.streak",
                    value=streak,
                    unit="text",
                    label=f"{s.label}: the run of consecutive moves ending at the latest period",
                    provenance=f"consecutive period-over-period signs across {s.row_a1}",
                    fmt="text",
                )
            )

    facts += _mover_facts(table)
    facts += _headline_facts(table)
    return FactSet(facts)


def materiality(series: Series) -> Decimal:
    """How much this line matters to the report, largest first.

    Revenue lines dominate a finance narrative and headcount does not, so the
    ordering is by absolute size within the currency lines. Without this the
    model reads the fact table in whatever order it is given and leads with
    whichever line happens to be first, an early live run opened a P&L summary
    with headcount while an eight-figure revenue line went unmentioned.
    """
    if not series.present:
        return Decimal(0)
    weight = {"currency": Decimal(1000), "number": Decimal(1), "percent": Decimal(0)}
    return max(abs(v) for v in series.present) * weight.get(series.unit, Decimal(1))


def _headline_facts(table: Table) -> list[Fact]:
    """Name the line the report should lead with."""
    ranked = sorted(table.series, key=lambda s: (materiality(s), s.slug), reverse=True)
    lead = next((s for s in ranked if s.present), None)
    if lead is None:
        return []
    return [
        Fact(
            key="headline.name",
            value=lead.label,
            unit="text",
            label="The most material line item, lead the summary with this one",
            provenance=lead.row_a1,
            fmt="text",
        )
    ]


_ORDINALS = {
    2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth",
    7: "seventh", 8: "eighth", 9: "ninth", 10: "tenth", 11: "eleventh",
    12: "twelfth",
}


def describe_streak(values: list[Decimal]) -> str | None:
    """How many consecutive periods have moved the same way, in words.

    This exists because of a real failure. The model wrote "marking the fourth
    consecutive period of growth" on its own: the figure it used was grounded,
    but the *claim that the growth was consecutive* was its own inference and
    nothing checked it. Grounding numbers is not enough if the sentence around
    them can still assert a pattern that was never verified.

    So the pattern becomes a fact too, computed by walking backwards from the
    latest period. Returns ``None`` when there is no run to describe, which
    leaves the model with no token and therefore nothing it is allowed to say.
    """
    if len(values) < 3:
        return None  # two points is a change, not a trend

    deltas = [b - a for a, b in zip(values, values[1:], strict=False)]
    last = deltas[-1]
    if last == 0:
        return None

    rising = last > 0
    run = 0
    for delta in reversed(deltas):
        if (delta > 0) == rising and delta != 0:
            run += 1
        else:
            break

    if run < 2:
        return None  # a single move is not a run

    word = "growth" if rising else "decline"
    ordinal = _ORDINALS.get(run)
    if ordinal is None:
        return f"part of a long unbroken run of {word}"
    return f"the {ordinal} consecutive period of {word}"


def magnitude_band(pct: Decimal) -> str:
    """Describe the size of a move in words, deterministically.

    This exists so that qualitative language is a *fact* rather than the model's
    opinion. It matters on re-runs: when a figure moves enough to turn "edged
    up" into "jumped", the band changes, the section's text facts change, and
    the incremental planner knows the sentence must be rewritten rather than
    merely re-substituted.

    Returned as a bare adverb so it composes with ``direction`` into one clause
   , "increased sharply". An earlier version returned a full phrase and the
    model dutifully produced "increased moved materially".
    """
    size = abs(pct)
    if size < Decimal("2"):
        return "marginally"
    if size < Decimal("10"):
        return "modestly"
    if size < Decimal("25"):
        return "materially"
    return "sharply"


def _safe_pct(delta: Decimal, base: Decimal) -> Decimal | None:
    """Percent change, or ``None`` when the base makes it meaningless.

    A move from zero is not "infinite growth" and must not be reported as a
    number at all, the narrative planner simply gets no ``delta_pct`` fact for
    that series and has to describe the move in words.
    """
    try:
        if base == 0:
            return None
        return (delta / abs(base)) * Decimal(100)
    except (DivisionByZero, InvalidOperation):
        return None


def _mover_facts(table: Table) -> list[Fact]:
    """Identify the largest proportional move in the selection."""
    ranked: list[tuple[Decimal, Series]] = []
    for s in table.series:
        prev, latest = s.previous, s.latest
        if prev is None or latest is None or prev == 0:
            continue
        pct = _safe_pct(latest - prev, prev)
        if pct is not None:
            ranked.append((abs(pct), s))

    if not ranked:
        return []

    ranked.sort(key=lambda pair: (pair[0], pair[1].slug), reverse=True)
    top = ranked[0][1]
    pct = _safe_pct(top.latest - top.previous, top.previous)
    return [
        Fact(
            key="top_mover.name",
            value=top.label,
            unit="text",
            label="Line item with the largest proportional move",
            provenance=top.row_a1,
            fmt="text",
        ),
        Fact(
            key="top_mover.delta_pct",
            value=pct,
            unit="percent",
            label="Size of the largest proportional move",
            provenance=f"{top.row_a1} period-over-period",
            fmt="signed_percent1",
        ),
    ]


def fact_table_for_model(facts: FactSet, table: Table | None = None) -> str:
    """Render the fact table that gets handed to the language model.

    Shows the *formatted* value so the model can judge tone and length, while
    the token remains the only way to put a number in the document.

    Ordered by materiality when the table is available: global facts first, then
    each line item most-significant first. Order is the only steer the model
    gets about what matters, and alphabetical order is not a steer at all.
    """
    from .numbers import format_fact

    rank: dict[str, int] = {}
    if table is not None:
        for position, s in enumerate(
            sorted(table.series, key=lambda x: (materiality(x), x.slug), reverse=True)
        ):
            rank[s.slug] = position

    def sort_key(key: str) -> tuple[int, int, str]:
        if not key.startswith("series."):
            return (0, 0, key)  # period, table and headline facts lead
        slug = key.split(".")[1]
        return (1, rank.get(slug, len(rank)), key)

    lines = ["| token | means | value |", "| --- | --- | --- |"]
    for key in sorted(facts, key=sort_key):
        fact = facts[key]
        lines.append(f"| {fact.token} | {fact.label} | {format_fact(fact)} |")
    return "\n".join(lines)
