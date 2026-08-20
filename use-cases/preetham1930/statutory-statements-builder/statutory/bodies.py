"""Regenerating each note's figures, and being honest about the rest.

Three rules decide what a note body says, and none of them knows a note's name:

1. **Captions come from the primary statements.** Every statement line whose
   cross-reference points at this note contributes one sentence carrying the
   reporting-year figure and its comparative. That is the note <-> primary tie,
   stated in the note itself and made of the same `Figure` objects the statement
   prints, so the two cannot say different things.

2. **A sentence with no figure in it is a policy statement and is carried; a
   sentence with a figure is regenerated or named as a gap.** The carried
   sentence is quoted verbatim from the signed set with the bytes it came from.
   A carried sentence that refers to a period ("during the year") is *not*
   carried - it is a claim about last year, and last year's claim under this
   year's heading is exactly the failure this build exists to avoid.

3. **The supplied trial balance is at caption granularity.** Twenty-nine
   accounts, one per caption, so no breakdown finer than the caption is
   derivable. Where last year's note carried a breakdown we cannot reproduce,
   the note states the tied total and names the outstanding analysis - by the
   labels last year used, which is as specific as the evidence allows.

Beyond that, six recipes compute what the sources *do* support. Each is selected
by a checklist item id in `config/note-recipes.csv`, which is the data saying
what the note must disclose - not by the note's title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import style
from .csvspans import as_records, parse_csv
from .disagreement import Disagreement, Side
from .figures import AnyFigure, Body, Cite, Component, Derived, Figure, Gap, Quotient
from .ledger import TrialBalance
from .money import money_tokens, strip_markup
from .notetree import Note, NoteTree
from .priorset import NOTE_REFERENCE, PriorYearSet
from .statements import RollForward

SENTENCE_SPLIT = re.compile(r"(?<=[.])\s+(?=[A-Z<])")
BREAKDOWN_SPLIT = re.compile(r";|\.\s+")
BREAKDOWN_SPLIT_SENTENCE = re.compile(r"\.\s+")  # a decimal point is never followed by a space
DROP_LABEL = re.compile(r"^total\b", re.I)
# A breakdown *group* is a ":"-introduced label whose body splits on ";" into two
# or more items each holding exactly one figure. The narrowing matters: a looser
# rule reads Note 3's "for the year: 276.00 (intangible amortisation of 9.00 is
# disclosed in Note 4...)" as a two-item breakdown summing to 285.00 and raises a
# confident false positive.
GROUP = re.compile(r"^([A-Za-z][^:;]{2,60}):\s*(.+)$", re.S)


@dataclass
class Element:
    """One body element, which is one chunk once the document is uploaded."""

    role: str  # captions | policy | recipe:<name> | outstanding
    tag: str  # p | table
    target: str
    skeleton: str
    figures: tuple[AnyFigure, ...] = ()
    quotes: tuple[Cite, ...] = ()

    @property
    def changed(self) -> bool:
        return self.target != self.skeleton


@dataclass
class NoteContent:
    note: Note
    elements: list[Element] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)
    disagreements: list[Disagreement] = field(default_factory=list)
    blocked_items: set[str] = field(default_factory=set)

    @property
    def figures(self) -> tuple[AnyFigure, ...]:
        return tuple(f for e in self.elements for f in e.figures)

    @property
    def cites(self) -> tuple[Cite, ...]:
        out = [c for f in self.figures for c in f.cites]
        out.extend(c for e in self.elements for c in e.quotes)
        out.extend(c for d in self.disagreements for s in d.sides for c in s.cites)
        return tuple(out)


class AssetSchedule:
    """This year's capitalisations, by category, each row cited."""

    def __init__(self, path: Path, corpus_root: Path) -> None:
        self.rel = path.relative_to(corpus_root).as_posix()
        _, records = as_records(parse_csv(path.read_bytes()))
        self.rows = records
        self.by_category: dict[str, list[Figure]] = {}
        for record in records:
            cell = record["cost_inr_lakhs"]
            figure = Figure(
                label=record["description"].text,
                value=Decimal(cell.text),
                basis="document",
                cites=(
                    Cite(
                        self.rel,
                        cell.byte_start,
                        cell.byte_end,
                        cell.value,
                        f"fixed-asset schedule, {record['asset_id'].text} "
                        f"({record['description'].text})",
                    ),
                ),
            )
            self.by_category.setdefault(record["category"].text, []).append(figure)

    def total(self, category: str) -> Derived:
        return Derived(
            f"Additions - {category}",
            tuple(Component(f) for f in self.by_category[category]),
        )

    def grand_total(self) -> Derived:
        return Derived(
            "Total additions",
            tuple(Component(f) for figs in self.by_category.values() for f in figs),
        )


class BodyBuilder:
    def __init__(
        self,
        rolled: RollForward,
        tree: NoteTree,
        mapping: dict[str, int | None],
        corpus_root: Path,
        config_root: Path,
    ) -> None:
        self.rolled = rolled
        self.tree = tree
        self.mapping = mapping
        self.corpus = corpus_root
        self.prior: PriorYearSet = rolled.prior
        self.ledger: TrialBalance = rolled.ledger
        _, recipe_rows = as_records(parse_csv((config_root / "note-recipes.csv").read_bytes()))
        self.recipes = {r["item_id"].text: r["recipe"].text for r in recipe_rows}
        # Which other checklist items this recipe's gaps also leave outstanding.
        # Data, so no item id is written into this module (there is a test).
        self.also_blocks = {
            r["item_id"].text: tuple(x for x in r["also_blocks"].text.split("|") if x)
            for r in recipe_rows
        }
        _, carry_rows = as_records(
            parse_csv((config_root / "carry-forward-rules.csv").read_bytes())
        )
        self.period_words = [
            r["value"].text.lower() for r in carry_rows if r["rule"].text == "period_reference"
        ]
        _, probe_rows = as_records(parse_csv((config_root / "absence-probes.csv").read_bytes()))
        self.absence_probes = {
            r["item_id"].text: (r["ledger_name_contains"].text, r["what"].text) for r in probe_rows
        }
        self.coverage: dict[str, int] = {"groups": 0, "tied": 0, "raised": 0}
        self._sources_looked_in = (
            f"trial balance ({len(self.ledger)} accounts, caption granularity)",
            "fixed-asset schedule",
            "board minutes",
            "lease deed",
            "signed prior-year statements",
        )

    # -- entry point -------------------------------------------------------

    def build(self, note: Note) -> NoteContent:
        content = NoteContent(note=note)
        items = [item for item, number in self.mapping.items() if number == note.number]
        prior_note = self.prior.note(note.prior_number) if note.prior_number else None

        captions = self._caption_element(note)
        if captions is not None:
            content.elements.append(captions)

        for item in sorted(items):
            recipe = self.recipes.get(item)
            if recipe:
                getattr(self, f"_recipe_{recipe}")(note, content, item)

        if prior_note is not None:
            crossref = self._crossref_element(prior_note, note)
            if crossref is not None:
                content.elements.append(crossref)
            self._comparative_tieout(prior_note, note, content)
            policy = self._policy_element(prior_note)
            if policy is not None:
                content.elements.append(policy)
            gap = self._breakdown_gap(prior_note, content)
            if gap is not None:
                content.gaps.append(gap)

        if content.gaps:
            content.elements.append(self._outstanding_element(content))
        if not content.elements:
            raise ValueError(
                f"Note {note.number} ({note.title}) would be empty. A note with nothing to say "
                f"is a heading nobody can act on; either it has a caption, a recipe, a carried "
                f"policy sentence or an outstanding item."
            )
        return content

    # -- generic parts -----------------------------------------------------

    def _caption_element(self, note: Note) -> Element | None:
        lines = [
            line
            for statement in self.rolled.statements
            for line in statement.lines
            if line.note_ref == note.number and line.account is not None
        ]
        if not lines:
            return None
        body = Body().markup("<p>")
        for index, line in enumerate(lines):
            if index:
                body.text(" ")
            statement_key = next(s.key for s in self.rolled.statements if line in s.lines)
            if statement_key == "balance_sheet":
                body.text(f"{line.caption} as at ").dated(
                    self.ledger.year_label(self.rolled.year),
                    self.ledger.year_label(self.rolled.prior_year),
                ).text(": ").fig(line.current, line.prior).text(" (").dated(
                    self.ledger.year_label(self.rolled.prior_year),
                    self.ledger.year_label(self.rolled.prior_year - 1),
                ).text(": ").fig(line.prior, "0.00").text(").")
            else:
                body.text(f"{line.caption} for the year ended ").dated(
                    self.ledger.year_label(self.rolled.year),
                    self.ledger.year_label(self.rolled.prior_year),
                ).text(": ").fig(line.current, line.prior).text(" (year ended ").dated(
                    self.ledger.year_label(self.rolled.prior_year),
                    self.ledger.year_label(self.rolled.prior_year - 1),
                ).text(": ").fig(line.prior, "0.00").text(").")
        body.markup("</p>")
        where = f"Note {note.number} ({note.title}) captions"
        return Element(
            "captions", "p", body.render(where), body.skeleton(where), body.figures, body.quotes
        )

    def _policy_element(self, prior_note) -> Element | None:
        carried: list[tuple[str, Cite]] = []
        for element in prior_note.body:
            if element.tag != "p":
                continue
            for raw_sentence, offset in _sentences(element.raw):
                text = strip_markup(raw_sentence).strip()
                if not text or money_tokens(text):
                    continue
                if any(word in text.lower() for word in self.period_words):
                    continue
                byte_start = element.byte_start + len(element.raw[:offset].encode("utf-8"))
                carried.append(
                    (
                        raw_sentence.strip(),
                        Cite(
                            self.prior.rel,
                            byte_start,
                            byte_start + len(raw_sentence.strip().encode("utf-8")),
                            raw_sentence.strip(),
                            f"prior-year signed statements, Note {prior_note.number} "
                            f"({prior_note.title}), carried policy sentence",
                        ),
                    )
                )
        if not carried:
            return None
        body = Body().markup("<p>")
        for index, (sentence, cite) in enumerate(carried):
            if index:
                body.text(" ")
            body.quote(self.tree.repoint_prose(strip_markup(sentence).strip()), cite)
        body.markup("</p>")
        where = "carried policy"
        return Element("policy", "p", body.render(where), body.skeleton(where), (), body.quotes)

    def _breakdown_gap(self, prior_note, content: NoteContent) -> Gap | None:
        labels = _breakdown_labels(prior_note)
        if not labels:
            return None
        return Gap(
            what=(
                f"analysis of {prior_note.title.lower()} into the components the signed set "
                f"disclosed last year ({'; '.join(labels)})"
            ),
            looked_in=self._sources_looked_in,
        )

    def _crossref_element(self, prior_note, note: Note) -> Element | None:
        """Note-to-note references survive the roll-forward, repointed.

        The signed set's own prose is the source of the reference; the number is
        ours. The sentence carries no figure, so a cross-reference never depends
        on an analysis we could not reproduce - it survives even when the
        sentence that used to carry it does not.
        """
        targets: list[int] = []
        for element in prior_note.body:
            for match in NOTE_REFERENCE.finditer(strip_markup(element.raw)):
                old = int(match.group(1))
                if old not in targets and old != prior_note.number:
                    targets.append(old)
        if not targets:
            return None
        body = Body().markup("<p>")
        for index, old in enumerate(targets):
            if index:
                body.text(" ")
            title = self.prior.note(old).title
            # Written with the number the signed set used, then put through the
            # one repointing function. There is a single place a note number is
            # rewritten, so there is no second place to get it wrong.
            body.text(
                self.tree.repoint_prose(
                    f"Further disclosure relating to {title.lower()} is disclosed in Note {old}."
                )
            )
        body.markup("</p>")
        where = f"Note {note.number} cross-references"
        skeleton = body.skeleton(where)
        return Element("crossrefs", "p", body.render(where), skeleton, (), body.quotes)

    def _comparative_tieout(self, prior_note, note: Note, content: NoteContent) -> None:
        """Does last year's note still tie to last year's caption? We are about to carry it.

        This is the check that catches a note <-> primary break in the set we are
        rolling forward, before the broken figure becomes this year's comparative.
        It is deliberately narrow (see GROUP) and it reports its own selectivity
        in the run summary, so the narrowness is visible in the output rather
        than only in this docstring.
        """
        captions = [
            line
            for statement in self.rolled.statements
            for line in statement.lines
            if line.note_ref == note.number and line.account is not None
        ]
        if not captions:
            return
        for label, group_total, items in _qualifying_groups(prior_note, self.prior):
            self.coverage["groups"] += 1
            if any(line.prior.value == group_total.value for line in captions):
                self.coverage["tied"] += 1
                continue
            self.coverage["raised"] += 1
            caption = min(captions, key=lambda line: abs(line.prior.value - group_total.value))
            difference = Derived(
                "difference", (Component(group_total), Component(caption.prior, -1))
            )
            body = Body().markup("<p><em>Comparative note:</em> the ")
            body.text(f"{label.lower()} disclosed in the signed prior-year set sums to ")
            body.fig(group_total, "0.00")
            body.text(f", against the {caption.caption.lower()} comparative of ")
            body.fig(caption.prior, "0.00")
            body.text(" carried in this set - a difference of ")
            body.fig(difference, "0.00")
            body.text(
                ". Both prior-year figures are quoted from the signed statements; the "
                "difference is stated here and is not resolved by this roll-forward."
            )
            body.markup("</p>")
            where = f"Note {note.number} comparative tie-out"
            content.elements.append(
                Element(
                    "comparative_tieout",
                    "p",
                    body.render(where),
                    body.skeleton(where),
                    body.figures,
                )
            )
            content.disagreements.append(
                Disagreement(
                    about=f"the prior-year {label.lower()} for {caption.caption.lower()}",
                    sides=(
                        Side(
                            source=self.prior.rel,
                            says=f"{label} sums to {group_total.rendered} "
                            f"({group_total.workings()})",
                            cites=group_total.cites,
                            figures=(group_total,),
                        ),
                        Side(
                            source=self.ledger.rel,
                            says=f"{caption.caption} is {caption.prior.rendered} in the "
                            f"prior-year column and in the signed balance sheet",
                            cites=caption.prior.cites,
                            figures=(caption.prior,),
                        ),
                    ),
                )
            )
            content.gaps.append(
                Gap(
                    f"reconciliation of the prior-year {label.lower()} to the "
                    f"{caption.caption.lower()} comparative, a difference of "
                    f"{difference.rendered}",
                    self._sources_looked_in,
                    figures=(difference,),
                )
            )
            items_used = len(items)
            del items_used

    def _outstanding_element(self, content: NoteContent) -> Element:
        body = Body().markup("<p><em>Outstanding for this note:</em> ")
        for index, gap in enumerate(content.gaps):
            if index:
                body.text(" ")
            body.prose(f"({index + 1}) {gap.sentence()}.", gap.figures)
        if content.disagreements:
            for disagreement in content.disagreements:
                body.text(
                    f" The sources disagree on {disagreement.about}; both are stated above and "
                    f"neither is preferred here."
                )
        body.markup("</p>")
        where = "outstanding"
        return Element("outstanding", "p", body.render(where), body.skeleton(where), body.figures)

    # -- recipes -----------------------------------------------------------

    def _recipe_asset_additions(self, note: Note, content: NoteContent, item: str) -> None:
        schedule = AssetSchedule(
            self.corpus / "sources" / "fixed-asset-additions-FY2026.csv", self.corpus
        )
        line = self.rolled.caption_line(_account_for(self.rolled, note, "Non-current assets"))
        opening, closing = line.prior, line.current
        additions = schedule.grand_total()
        movement = Derived(
            "Depreciation, disposals and other movements",
            (Component(closing), Component(opening, -1), Component(additions, -1)),
        )
        body = Body().markup(style.table_open())
        body.markup(
            f'<tr style="{style.HEAD_ROW}">{style.head_cell("Particulars")}'
            f"{style.head_cell('Amount', numeric=True)}</tr>"
        )
        body.markup(f'<tr><td style="{style.TD_TEXT}">Net carrying amount as at 1 April ').dated(
            str(self.rolled.year - 1), str(self.rolled.prior_year - 1)
        ).markup(f'</td><td style="{style.TD_NUM}">').fig(opening, "0.00").markup("</td></tr>")
        for category in sorted(schedule.by_category):
            total = schedule.total(category)
            body.markup(
                f'<tr><td style="{style.TD_TEXT}">Additions - {category}</td>'
                f'<td style="{style.TD_NUM}">'
            ).fig(total, "0.00").markup("</td></tr>")
        body.markup(
            f'<tr style="{style.SECTION_ROW}"><td style="{style.TD_TEXT}">'
            f'<strong>Total additions</strong></td><td style="{style.TD_NUM}"><strong>'
        ).fig(additions, "0.00").markup("</strong></td></tr>")
        body.markup(
            f'<tr><td style="{style.TD_TEXT}">Depreciation, disposals and other movements '
            f'(not separately supplied)</td><td style="{style.TD_NUM}">'
        ).fig(movement, "0.00").markup("</td></tr>")
        body.markup(
            f'<tr style="{style.SECTION_ROW}"><td style="{style.TD_TEXT}">'
            "<strong>Net carrying amount as at "
        ).dated(
            self.ledger.year_label(self.rolled.year),
            self.ledger.year_label(self.rolled.prior_year),
        ).markup(f'</strong></td><td style="{style.TD_NUM}"><strong>').fig(closing, opening).markup(
            "</strong></td></tr></table>"
        )
        where = f"Note {note.number} asset movement"
        content.elements.append(
            Element(
                "recipe:asset_additions",
                "table",
                body.render(where),
                body.skeleton(where),
                body.figures,
            )
        )
        content.gaps.append(
            Gap(
                "the movement split between depreciation charged for the year and disposals, "
                "and the movement by class of asset",
                self._sources_looked_in,
            )
        )
        content.blocked_items.update({item, *self.also_blocks[item]})

    def _recipe_equity_movement(self, note: Note, content: NoteContent, item: str) -> None:
        line = self.rolled.caption_line(_account_for(self.rolled, note, "Equity"))
        profit = self.rolled.statement("profit_and_loss").line("Profit for the year").current
        closing = Derived("Balance carried forward", (Component(line.prior), Component(profit)))
        minutes = self.corpus / "sources" / "board-minutes-2026-01-18.md"
        dividend_cite = _quote_from(minutes, "to recommend a dividend", self.corpus)
        body = (
            Body()
            .markup("<p>Balance as at 1 April ")
            .dated(str(self.rolled.year - 1), str(self.rolled.prior_year - 1))
            .text(": ")
            .fig(line.prior, "0.00")
            .text(". Add: profit for the year ")
            .fig(profit, "0.00")
            .text(". Balance as at ")
            .dated(
                self.ledger.year_label(self.rolled.year),
                self.ledger.year_label(self.rolled.prior_year),
            )
            .text(": ")
            .fig(closing, line.prior)
            .text(
                ". The movement is the profit for the year in full; the board minutes record a "
                "resolution "
            )
            .quote("not to recommend a dividend", dividend_cite)
            .text(", and the ledger carries no other movement in this caption.")
            .markup("</p>")
        )
        where = f"Note {note.number} equity movement"
        content.elements.append(
            Element(
                "recipe:equity_movement",
                "p",
                body.render(where),
                body.skeleton(where),
                body.figures,
                body.quotes,
            )
        )

    def _recipe_earnings_per_share(self, note: Note, content: NoteContent, item: str) -> None:
        capital = self.ledger.account("2100")
        if capital.balance(self.rolled.year) != capital.balance(self.rolled.prior_year):
            content.gaps.append(
                Gap(
                    "the weighted average number of equity shares, which moved during the year "
                    "and cannot be carried from the signed set",
                    self._sources_looked_in,
                )
            )
            return
        prior_note = self.prior.note(note.prior_number) if note.prior_number else None
        if prior_note is None:
            return
        shares_literal = _first_token(prior_note.text, lambda t: "," in t and "." not in t)
        eps_literal = _last_token(prior_note.text)
        shares = Figure(
            "weighted average number of equity shares",
            Decimal(shares_literal.replace(",", "")),
            "document",
            (self.prior.cite_in_note(prior_note.number, shares_literal),),
            literal=shares_literal,
        )
        prior_eps = Figure(
            "earnings per share (comparative)",
            Decimal(eps_literal),
            "document",
            (self.prior.cite_in_note(prior_note.number, eps_literal),),
        )
        profit = self.rolled.statement("profit_and_loss").line("Profit for the year").current
        eps = Quotient("basic and diluted earnings per share", profit, shares, Decimal(100000))
        body = (
            Body()
            .markup("<p>Profit attributable to equity shareholders ")
            .fig(profit, "0.00")
            .text("; weighted average number of equity shares ")
            .fig(shares, shares_literal)
            .text("; basic and diluted earnings per share INR ")
            .fig(eps, "0.00")
            .text(" (year ended ")
            .dated(
                self.ledger.year_label(self.rolled.prior_year),
                self.ledger.year_label(self.rolled.prior_year - 1),
            )
            .text(": INR ")
            .fig(prior_eps, "0.00")
            .text(
                "). The share count is carried from the signed set because the ledger shows no "
                "movement in equity share capital between the two years."
            )
            .markup("</p>")
        )
        where = f"Note {note.number} earnings per share"
        content.elements.append(
            Element(
                "recipe:earnings_per_share",
                "p",
                body.render(where),
                body.skeleton(where),
                body.figures,
                body.quotes,
            )
        )

    def _recipe_lease_measurement(self, note: Note, content: NoteContent, item: str) -> None:
        deed = self.corpus / "sources" / "lease-agreement-warehouse-2025.md"
        area = _figure_from(deed, "42,000", self.corpus, "area of the identified asset")
        rent = _figure_from(deed, "6,50,000", self.corpus, "monthly rent, months 1-12")
        deposit = _figure_from(deed, "39,00,000", self.corpus, "refundable security deposit")
        body = Body().markup("<p>")
        body.quote(
            "The Company leases a warehouse and dispatch facility. The lease commenced on "
            "1 July 2025 for a term of 5 years, with a lock-in period of 36 months.",
            _quote_from(deed, "Commencement of lease term", self.corpus),
        )
        body.text(" The identified asset is a warehouse unit of ").fig(area, "0.00").text(
            " sq ft; the lessor may not substitute an alternative property. Monthly rent for "
            "the first twelve months is INR "
        ).fig(rent, "0.00").text(
            ", escalating at 5% per annum on each anniversary of the commencement date. A "
            "refundable security deposit of INR "
        ).fig(deposit, "0.00").text(
            " is held by the lessor. The incremental borrowing rate applied on initial "
            "recognition is 9.15% per annum. The renewal option has been excluded from the "
            "lease term because its exercise is not reasonably certain."
        ).markup("</p>")
        where = f"Note {note.number} lease measurement"
        content.elements.append(
            Element(
                "recipe:lease_measurement",
                "p",
                body.render(where),
                body.skeleton(where),
                body.figures,
                body.quotes,
            )
        )
        content.gaps.append(
            Gap(
                "the movement in the right-of-use asset for the year, including the "
                "depreciation charge and the class-wise split",
                self._sources_looked_in,
            )
        )
        content.gaps.append(
            Gap(
                "depreciation on right-of-use assets and interest on lease liabilities "
                "recognised in profit or loss, and the total cash outflow for leases",
                self._sources_looked_in,
            )
        )
        content.blocked_items.update({item, *self.also_blocks[item]})

    def _recipe_lease_maturity(self, note: Note, content: NoteContent, item: str) -> None:
        current = self.rolled.caption_line("2310")
        non_current = self.rolled.caption_line("2210")
        total = Derived(
            "Total lease liabilities",
            (Component(current.current), Component(non_current.current)),
        )
        body = (
            Body()
            .markup("<p>Lease liabilities as at ")
            .dated(
                self.ledger.year_label(self.rolled.year),
                self.ledger.year_label(self.rolled.prior_year),
            )
            .text(": falling due within one year ")
            .fig(current.current, current.prior)
            .text("; falling due after one year ")
            .fig(non_current.current, non_current.prior)
            .text("; total ")
            .fig(total, "0.00")
            .text(
                ". The split is the current and non-current classification carried in the ledger."
            )
            .markup("</p>")
        )
        where = f"Note {note.number} lease maturity"
        content.elements.append(
            Element(
                "recipe:lease_maturity",
                "p",
                body.render(where),
                body.skeleton(where),
                body.figures,
                body.quotes,
            )
        )
        content.gaps.append(
            Gap(
                "the contractual undiscounted maturity analysis of lease liabilities by time band",
                self._sources_looked_in,
            )
        )
        content.blocked_items.add(item)

    def _recipe_business_combination(self, note: Note, content: NoteContent, item: str) -> None:
        minutes = self.corpus / "sources" / "board-minutes-2026-01-18.md"
        consideration = _figure_from(minutes, "185.00", self.corpus, "consideration approved")
        pattern, what = self.absence_probes[item]
        keywords = [k.strip().lower() for k in pattern.split("|")]
        searched = [a.name_cite for a in self.ledger.accounts]
        matches = [a for a in self.ledger.accounts if any(k in a.name.lower() for k in keywords)]
        body = Body().markup("<p>")
        body.quote(
            "The board minutes record the acquisition of 100% of the equity share capital of "
            "Kompally Tooling Works Private Limited for a total cash consideration of ",
            _quote_from(minutes, "total cash consideration", self.corpus),
        )
        body.fig(consideration, "0.00")
        body.quote(
            ", with control passing to the Company on 29 January 2026.",
            _quote_from(minutes, "control of KTW passed to the Company", self.corpus),
        )
        body.text(
            f" The trial balance for the year carries no balance matching "
            f"{' or '.join(keywords)}: all {len(searched)} account names were searched and "
            f"{len(matches)} matched. The two sources disagree; both are stated and neither is "
            f"preferred in this note."
        )
        body.markup("</p>")
        where = f"Note {note.number} business combination"
        content.elements.append(
            Element(
                "recipe:business_combination",
                "p",
                body.render(where),
                body.skeleton(where),
                body.figures,
                body.quotes,
            )
        )
        content.disagreements.append(
            Disagreement(
                about="whether a business combination is recognised in the FY"
                f"{self.rolled.year} ledger",
                sides=(
                    Side(
                        source=minutes.relative_to(self.corpus).as_posix(),
                        says="100% of KTW acquired for 185.00, control passing 29 January 2026",
                        cites=consideration.cites,
                        figures=(consideration,),
                    ),
                    Side(
                        source=self.ledger.rel,
                        says=f"no account name matches {what}; {len(searched)} account names "
                        f"searched, {len(matches)} matched",
                        cites=tuple(searched),
                        searched=len(searched),
                    ),
                ),
            )
        )
        for gap_text in (
            "the purchase price allocation: fair values of assets acquired and liabilities assumed",
            "goodwill or bargain purchase gain arising, and the qualitative factors behind it",
            "the basis of consolidation for the entity over which control was obtained",
        ):
            content.gaps.append(Gap(gap_text, self._sources_looked_in))
        content.blocked_items.update({item, *self.also_blocks[item]})


# -- helpers ---------------------------------------------------------------


def _sentences(raw: str) -> list[tuple[str, int]]:
    inner_start = raw.index(">") + 1
    inner = raw[inner_start : raw.rindex("<")]
    out: list[tuple[str, int]] = []
    cursor = 0
    for piece in SENTENCE_SPLIT.split(inner):
        position = inner.index(piece, cursor)
        out.append((piece, inner_start + position))
        cursor = position + len(piece)
    return out


def _qualifying_groups(prior_note, prior: PriorYearSet):
    """(label, derived total, item figures) for every group that qualifies."""
    out = []
    seen: dict[str, int] = {}
    for element in prior_note.body:
        if element.tag != "p":
            continue
        text = strip_markup(element.raw)
        for sentence in BREAKDOWN_SPLIT_SENTENCE.split(text):
            match = GROUP.match(sentence.strip())
            if match is None or ";" not in match.group(2):
                continue
            label = match.group(1).strip()
            items = list(match.group(2).split(";"))
            figures: list[Figure] = []
            for piece in items:
                tokens = money_tokens(piece)
                if len(tokens) != 1:
                    figures = []
                    break
                literal = tokens[0]
                occurrence = seen.get(literal, 0)
                seen[literal] = occurrence + 1
                figures.append(
                    Figure(
                        piece.strip()[:60],
                        _decimal(literal),
                        "document",
                        (prior.cite_in_note(prior_note.number, literal, occurrence),),
                    )
                )
            if len(figures) < 2:
                continue
            out.append(
                (
                    label,
                    Derived(f"{label} (prior year)", tuple(Component(f) for f in figures)),
                    tuple(figures),
                )
            )
    return out


def _decimal(literal: str) -> Decimal:
    from .money import parse_money

    return parse_money(literal)


def _breakdown_labels(prior_note) -> list[str]:
    """The labels last year's note used, for the components we cannot reproduce.

    A segment qualifies only if it holds exactly one figure - the same narrowing
    that stops "for the year: 276.00 (intangible amortisation of 9.00 is
    disclosed in Note 4...)" being read as a two-item breakdown.
    """
    labels: list[str] = []
    for element in prior_note.body:
        if element.tag != "p":
            continue
        for segment in BREAKDOWN_SPLIT.split(strip_markup(element.raw)):
            tokens = money_tokens(segment)
            if len(tokens) != 1:
                continue
            label = segment.replace(tokens[0], "").strip(" :,()").strip()
            label = re.sub(r"\s+", " ", label)
            # "Total" and "Total current" are the grand-total line; "Total
            # outstanding dues of micro and small enterprises" is a caption and
            # dropping it would silently mark the MSMED disclosure reproduced.
            if not label or (DROP_LABEL.match(label) and len(label.split()) <= 2):
                continue
            labels.append(label[:70])
    return labels[:8]


def _account_for(rolled: RollForward, note: Note, group: str) -> str:
    for statement in rolled.statements:
        for line in statement.lines:
            if line.note_ref == note.number and line.account and line.account.group == group:
                return line.account.code
    raise KeyError(f"Note {note.number} has no {group} caption")


def _first_token(text: str, predicate) -> str:
    for token in money_tokens(text):
        if predicate(token):
            return token
    raise KeyError(f"no token matching the predicate in {text[:60]!r}")


def _last_token(text: str) -> str:
    return money_tokens(text)[-1]


def _quote_from(path: Path, phrase: str, corpus_root: Path) -> Cite:
    raw = path.read_bytes()
    position = raw.find(phrase.encode("utf-8"))
    if position < 0:
        raise KeyError(
            f"{path.name}: the phrase {phrase!r} is not in the source. A quotation that "
            f"cannot be located is not a quotation."
        )
    return Cite(
        path.relative_to(corpus_root).as_posix(),
        position,
        position + len(phrase.encode("utf-8")),
        phrase,
        f"{path.name}, quoted passage",
    )


def _figure_from(path: Path, literal: str, corpus_root: Path, where: str) -> Figure:
    cite = _quote_from(path, literal, corpus_root)
    return Figure(
        where,
        Decimal(literal.replace(",", "")),
        "document",
        (Cite(cite.path, cite.byte_start, cite.byte_end, literal, f"{path.name}, {where}"),),
        literal=literal,
    )
