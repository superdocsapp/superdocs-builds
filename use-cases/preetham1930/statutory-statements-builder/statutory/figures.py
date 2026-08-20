"""Figures, their provenance, and the guarantee that nothing else reaches paper.

Four bases and there is no fifth (INVARIANTS.md item 6):

- `ledger`      the figure is a trial-balance cell for the reporting year
- `comparative` a prior-year figure, cited twice - to the ledger's prior-year
                column *and* to the signed prior-year statements - which is what
                makes "the comparatives tie exactly" a checked claim
- `document`    a figure quoted from a source document (the lease deed, the
                minutes, the fixed-asset schedule)
- `derived`     computed from figures that are themselves on one of the three
                bases above, every component cited

`Derived` has no `value` field. The total is a property recomputed on every
read, so a printed total cannot drift from the citations that support it and
cannot be stated apart from them. That is Decision 16's trick, rebuilt here
against a different substrate (Decision 31) - twenty lines, and copying it is
cheaper than any coupling.

`Gap` is the honest alternative to inventing an analysis: it names what is
missing and every place we looked for it.
"""

from __future__ import annotations

import html as _html
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .errors import CitationDriftError, UnaccountedFigureError
from .money import format_money, money_tokens_in_html

BASES = ("ledger", "comparative", "document", "derived")
SOURCE_BASES = ("ledger", "comparative", "document")


@dataclass(frozen=True)
class Cite:
    """A byte range in a corpus file that physically contains `snippet`."""

    path: str  # corpus-relative, forward slashes
    byte_start: int
    byte_end: int
    snippet: str
    where: str  # human location, e.g. "trial balance row 1110, column fy2026_inr_lakhs"

    def __post_init__(self) -> None:
        if self.byte_end < self.byte_start:
            raise ValueError(f"{self.path}: byte range runs backwards")
        if not self.snippet:
            raise ValueError(f"{self.path}: a citation with an empty snippet cites nothing")

    def read_back(self, root: Path) -> str:
        raw = (root / self.path).read_bytes()[self.byte_start : self.byte_end]
        return raw.decode("utf-8")

    def verify(self, root: Path) -> None:
        """Hard rule 2: re-read the bytes and confirm they still say what we cited."""
        actual = self.read_back(root)
        if actual != self.snippet:
            raise CitationDriftError(
                f"citation drift in {self.path} at bytes {self.byte_start}-{self.byte_end} "
                f"({self.where}): cited {self.snippet!r}, the file now holds {actual!r}"
            )


@dataclass(frozen=True)
class Figure:
    """One figure with its provenance and the exact string it is written as."""

    label: str
    value: Decimal
    basis: str
    cites: tuple[Cite, ...]
    literal: str | None = None  # when the source spells it differently (6,50,000)

    def __post_init__(self) -> None:
        if self.basis not in SOURCE_BASES:
            raise ValueError(
                f"{self.label}: basis {self.basis!r} is not one of {SOURCE_BASES}. "
                f"A derived total is a Derived, which has no value field."
            )
        if not self.cites:
            raise ValueError(
                f"{self.label}: a figure with no citation has no provenance and may not exist"
            )
        if self.basis == "comparative" and len(self.cites) < 2:
            raise ValueError(
                f"{self.label}: a comparative is cited twice - to the ledger's prior-year "
                f"column and to the signed prior-year statements - or it is not a comparative"
            )

    @property
    def rendered(self) -> str:
        return self.literal if self.literal is not None else format_money(self.value)


@dataclass(frozen=True)
class Component:
    figure: Figure | Derived
    sign: int = 1

    def __post_init__(self) -> None:
        if self.sign not in (1, -1):
            raise ValueError("a component contributes +1 or -1, nothing else")

    @property
    def contribution(self) -> Decimal:
        return self.sign * self.figure.value


@dataclass(frozen=True)
class Derived:
    """A total that appears in no source. Its value is computed, never stored."""

    label: str
    components: tuple[Component, ...]
    basis: str = field(default="derived", init=False)

    def __post_init__(self) -> None:
        if not self.components:
            raise ValueError(f"{self.label}: a derived figure with no components is a bare number")

    @property
    def value(self) -> Decimal:
        return sum((c.contribution for c in self.components), Decimal("0")).quantize(
            Decimal("0.01")
        )

    @property
    def rendered(self) -> str:
        return format_money(self.value)

    @property
    def cites(self) -> tuple[Cite, ...]:
        out: list[Cite] = []
        for component in self.components:
            out.extend(component.figure.cites)
        return tuple(out)

    def workings(self) -> str:
        parts = []
        for index, component in enumerate(self.components):
            sign = "-" if component.sign < 0 else ("+" if index else "")
            parts.append(f"{sign} {format_money(abs(component.figure.value))}".strip())
        return f"{' '.join(parts)} = {self.rendered}"


@dataclass(frozen=True)
class Gap:
    """What could not be produced, and every place we looked for it.

    Not a finding (INVARIANTS.md item 20): it is a property of the document -
    this note cannot state that analysis from the sources supplied.
    """

    what: str
    looked_in: tuple[str, ...]
    figures: tuple[AnyFigure, ...] = ()

    def __post_init__(self) -> None:
        if not self.what.strip():
            raise ValueError("a gap must say what is missing")
        if not self.looked_in:
            raise ValueError(
                f"{self.what}: a gap that does not say where we looked is a shrug, not a gap"
            )

    def sentence(self) -> str:
        return f"{self.what} (looked in: {', '.join(self.looked_in)})"


# --------------------------------------------------------------------------
# The body builder, and the guarantee
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Quotient:
    """A per-share figure. Division does not fit a signed sum, so it gets a type.

    `scale` is a declared unit conversion (lakhs to rupees), not a fudge factor,
    and it is written at the call site where the units are visible.
    """

    label: str
    numerator: AnyFigure
    denominator: AnyFigure
    scale: Decimal = Decimal(1)
    basis: str = field(default="derived", init=False)

    @property
    def value(self) -> Decimal:
        if self.denominator.value == 0:
            raise ZeroDivisionError(f"{self.label}: the denominator is nil")
        return (self.numerator.value * self.scale / self.denominator.value).quantize(
            Decimal("0.01")
        )

    @property
    def rendered(self) -> str:
        return format_money(self.value)

    @property
    def cites(self) -> tuple[Cite, ...]:
        return tuple(self.numerator.cites) + tuple(self.denominator.cites)


AnyFigure = Figure | Derived | Quotient


@dataclass(frozen=True)
class _Slot:
    """One figure as it appears twice: in the target, and in the skeleton."""

    target: str
    skeleton: str
    figure: AnyFigure | None


class Body:
    """A rendered fragment plus the figures that account for every token in it.

    Text goes through `text()`, markup through `markup()`, and every figure goes
    through `fig()`. Then `render()` re-scans its own output and refuses to
    return a fragment holding a token no figure accounts for.

    A body renders twice. `render()` is the FY figures we computed; `skeleton()`
    is the same structure carrying last year's, which is what gets uploaded
    (Decision 29). Both are scanned, and the plan only contains the chunks where
    the two differ - an identical chunk needs no edit and is never sent.
    """

    def __init__(self) -> None:
        self._parts: list[str | _Slot] = []
        self._figures: list[AnyFigure] = []
        self._quotes: list[Cite] = []

    def markup(self, raw: str) -> Body:
        self._parts.append(raw)
        return self

    def text(self, value: str) -> Body:
        self._parts.append(_html.escape(value, quote=False))
        return self

    def dated(self, target: str, skeleton: str) -> Body:
        """A label that differs between the two renderings, e.g. the year."""
        self._parts.append(
            _Slot(_html.escape(target, quote=False), _html.escape(skeleton, quote=False), None)
        )
        return self

    def fig(self, figure: AnyFigure, skeleton: AnyFigure | str | None = None) -> Body:
        self._figures.append(figure)
        if isinstance(skeleton, str):
            shadow = skeleton
        elif skeleton is None:
            shadow = format_money(Decimal(0))
        else:
            shadow = skeleton.rendered
        self._parts.append(
            _Slot(
                _html.escape(figure.rendered, quote=False),
                _html.escape(shadow, quote=False),
                figure,
            )
        )
        return self

    def prose(self, text: str, figures: tuple[AnyFigure, ...] = ()) -> Body:
        """Sentence text whose figures are named, emitted as figures where they occur.

        There is deliberately no "declare this figure without printing it" door:
        a figure only counts once its rendered string has actually been found in
        the sentence and emitted as a slot. A sentence that mentions a figure the
        caller did not declare still fails the scan.
        """
        remaining = text
        while remaining:
            hit = None
            for figure in figures:
                position = remaining.find(figure.rendered)
                if position >= 0 and (hit is None or position < hit[0]):
                    hit = (position, figure)
            if hit is None:
                self.text(remaining)
                return self
            position, figure = hit
            self.text(remaining[:position])
            self.fig(figure)
            remaining = remaining[position + len(figure.rendered) :]
        return self

    def quote(self, text: str, cite: Cite) -> Body:
        """Prose lifted from a source, with the bytes it came from recorded."""
        self._quotes.append(cite)
        self._parts.append(_html.escape(text, quote=False))
        return self

    def carried(self, raw_html: str, figures: tuple[AnyFigure, ...] = ()) -> Body:
        """Prose carried from the prior-year set verbatim, with its figures declared."""
        self._parts.append(raw_html)
        self._figures.extend(figures)
        return self

    @property
    def figures(self) -> tuple[AnyFigure, ...]:
        return tuple(self._figures)

    @property
    def quotes(self) -> tuple[Cite, ...]:
        return tuple(self._quotes)

    def _join(self, skeleton: bool) -> str:
        return "".join(
            (p.skeleton if skeleton else p.target) if isinstance(p, _Slot) else p
            for p in self._parts
        )

    def render(self, where: str) -> str:
        fragment = self._join(skeleton=False)
        assert_accounted(fragment, self._figures, where)
        return fragment

    def skeleton(self, where: str) -> str:
        """The same structure with last year's figures. Uploaded, then replaced."""
        fragment = self._join(skeleton=True)
        declared = [
            _Shadow(p.skeleton)
            for p in self._parts
            if isinstance(p, _Slot) and p.figure is not None
        ]
        assert_accounted(fragment, declared, f"{where} (skeleton)")
        return fragment


@dataclass(frozen=True)
class _Shadow:
    """A skeleton token. Carries no provenance because it never reaches an export."""

    rendered: str


def assert_accounted(fragment: str, figures: list[AnyFigure] | tuple[AnyFigure, ...], where: str):
    """Every money token in `fragment` is the rendered form of a declared figure.

    Counted as a multiset, so two nil balances need two figures. A token with no
    figure behind it is a hard error naming the token and the place - never a
    warning, never a caveat (hard rule 13).
    """
    found = Counter(money_tokens_in_html(fragment))
    declared = Counter(f.rendered for f in figures)
    unaccounted = found - declared
    if unaccounted:
        tokens = ", ".join(sorted(unaccounted.elements()))
        raise UnaccountedFigureError(
            f"{where}: {sum(unaccounted.values())} money token(s) reached the document with "
            f"no source behind them: {tokens}. "
            f"Declared figures were: {', '.join(sorted(declared.elements())) or '(none)'}. "
            f"Every figure is ledger, comparative, document or derived; there is no fifth "
            f"basis, and this is a hard error rather than a warning."
        )


def verify_all(figures: list[AnyFigure] | tuple[AnyFigure, ...], root: Path) -> int:
    """Re-read every citation off disk. Returns how many were checked."""
    checked = 0
    for figure in figures:
        for cite in figure.cites:
            cite.verify(root)
            checked += 1
    return checked
