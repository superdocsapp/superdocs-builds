"""Assembly: the intake picks the clauses, we number them, we render both fills.

Decision 29, stated as code for this build. Two renderings come out of one
structure:

- `skeleton` - the **blank form** for this intake's POA type, jurisdiction and
  granted categories. Every clause that will exist is already there, at its
  final number, with every cross-reference already pointing at the right one,
  and both notices already in place. Party names, the specific powers, the
  limitation and the commencement are blank-form markers.
- `target`   - the same document with the intake's answers filled in.

The skeleton is what gets uploaded, verbatim. So SuperDocs never inserts a
clause, never renumbers one, and never writes one: every instruction it receives
is "replace this chunk with exactly these bytes", and the bytes came from the
library. An invented clause has no channel to arrive through, which is the
structural argument rather than the checking one - the same shape as Decision 13
in `system/`.

Numbering is one pass over the selected clause list. It genuinely differs
between the two required drafts: the healthcare draft carries a clause the
financial one does not (`healthcare-records-access`, selected by
`category granted healthcare`), so every clause after it is numbered one higher
and the cross-reference in the reliance clause moves with it. Nothing about that
is asked of the product.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import style
from .chunks import strip_markup, tidy
from .errors import (
    CrossReferenceError,
    ForbiddenPhraseError,
    UnresolvedPlaceholderError,
)
from .intake import Intake
from .library import PLACEHOLDER, Clause, Library

CLAUSE_REFERENCE = re.compile(r"\bclause (\d+)\b")


@dataclass
class Block:
    """One top-level element, which becomes one chunk on upload."""

    role: str
    clause_id: str
    tag: str
    skeleton: str
    target: str
    clause_number: int | None = None
    is_notice: bool = False
    is_heading: bool = False

    def __post_init__(self) -> None:
        self.skeleton = tidy(self.skeleton)
        self.target = tidy(self.target)

    @property
    def changed(self) -> bool:
        return self.skeleton != self.target

    @property
    def editable(self) -> bool:
        """A heading carries the numbering and a notice carries the guarantee.
        Neither is ever the target of an instruction."""
        return not self.is_heading and not self.is_notice


@dataclass
class Draft:
    intake_id: str
    poa_type: str
    jurisdiction: str
    blocks: list[Block] = field(default_factory=list)
    numbering: dict[str, int] = field(default_factory=dict)
    granted: dict[str, tuple[str, ...]] = field(default_factory=dict)
    receipts: list[str] = field(default_factory=list)

    def html(self, which: str = "target") -> str:
        return "\n".join(getattr(b, which) for b in self.blocks)

    def editable_changed(self) -> list[Block]:
        return [b for b in self.blocks if b.editable and b.changed]

    def block(self, role: str) -> Block:
        return next(b for b in self.blocks if b.role == role)

    @property
    def filename(self) -> str:
        return f"poa-{self.intake_id}.html"


def assemble(intake: Intake, library: Library) -> Draft:
    categories = intake.categories(library)
    selected = library.select(intake.poa_type, categories)

    numbering = _number(selected)
    draft = Draft(
        intake_id=intake.intake_id,
        poa_type=intake.poa_type,
        jurisdiction=intake.jurisdiction,
        numbering=numbering,
        granted={c: intake.powers_in(library, c) for c in categories},
    )

    structural = _structural_values(intake, library)
    blank = dict(structural)
    filled = dict(structural)
    for placeholder, text in library.blank_form.items():
        blank[placeholder] = text
    filled.update(_instance_values(intake))

    running: int | None = None
    for clause in selected:
        if clause.numbered:
            number = numbering[clause.clause_id]
            running = number
            heading = style.wrap("h2", "heading", f"{number}. {clause.heading}")
            draft.blocks.append(
                Block(
                    role=f"{clause.clause_id}-heading",
                    clause_id=clause.clause_id,
                    tag="h2",
                    skeleton=heading,
                    target=heading,
                    clause_number=number,
                    is_heading=True,
                )
            )
        draft.blocks.append(
            Block(
                role=clause.clause_id,
                clause_id=clause.clause_id,
                tag=clause.tag,
                skeleton=_render(clause, blank, numbering, library, intake, filled=False),
                target=_render(clause, filled, numbering, library, intake, filled=True),
                # An unnumbered clause (a list, a description) belongs to the
                # numbered clause above it, which is how a reader reads it and
                # how the edit plan should describe it.
                clause_number=running,
                is_notice=clause.style_role == "notice",
            )
        )

    _assert_cross_references_resolve(draft, numbering)
    _assert_no_reference_moves_between_the_two_fills(draft)
    draft.receipts.append(assert_no_forbidden_phrase(draft, library))
    draft.receipts.append(
        f"{len(selected)} clause(s) selected from {len(library.clauses)} in the library by "
        f"type={intake.poa_type!r} and categories={list(categories)}; "
        f"{len(numbering)} numbered; {len(draft.editable_changed())} chunk(s) differ between "
        f"the blank form and the filled draft and become the edit plan"
    )
    return draft


# -- numbering and cross-references ---------------------------------------


def _number(selected: list[Clause]) -> dict[str, int]:
    """One pass over the selected clauses, in library order. Nothing is asked."""
    numbering: dict[str, int] = {}
    for clause in selected:
        if clause.numbered:
            numbering[clause.clause_id] = len(numbering) + 1
    return numbering


def _assert_cross_references_resolve(draft: Draft, numbering: dict[str, int]) -> None:
    numbers = set(numbering.values())
    for block in draft.blocks:
        if block.is_heading:
            continue
        for which in ("skeleton", "target"):
            for match in CLAUSE_REFERENCE.finditer(strip_markup(getattr(block, which))):
                referenced = int(match.group(1))
                if referenced not in numbers:
                    raise CrossReferenceError(
                        f"block {block.role!r} ({which}) points at clause {referenced}, which "
                        f"this draft does not have. It runs 1..{max(numbers) if numbers else 0}. "
                        f"Every reference is resolved through the same numbering pass that "
                        f"numbered the headings, so this is a bug in that pass, not a caveat."
                    )


def _assert_no_reference_moves_between_the_two_fills(draft: Draft) -> None:
    """A cross-reference is structure, so filling in a name may not move one.

    If it did, an edit would be renumbering, and renumbering delegated to the
    product is the failure this whole design exists to avoid (measured twice:
    the insert vanishes and the renumbers land around it).
    """
    for block in draft.blocks:
        before = CLAUSE_REFERENCE.findall(strip_markup(block.skeleton))
        after = CLAUSE_REFERENCE.findall(strip_markup(block.target))
        if before != after:
            raise CrossReferenceError(
                f"block {block.role!r} references clauses {before} in the blank form and "
                f"{after} once filled. A cross-reference is structure and is uploaded at its "
                f"final value; an edit that moved one would be a renumbering instruction."
            )


# -- the legal-adjacency scan ---------------------------------------------


def assert_no_forbidden_phrase(draft: Draft, library: Library) -> str:
    """INVARIANTS.md A2. Scanned over both fills, because both go to the wire.

    The blank form is the document that is actually uploaded, so a phrase that
    only appears there would reach the live document and never be looked at.
    """
    checked = 0
    for block in draft.blocks:
        for which in ("skeleton", "target"):
            text = strip_markup(getattr(block, which)).lower()
            checked += 1
            for forbidden in library.forbidden:
                if forbidden.phrase in text:
                    raise ForbiddenPhraseError(
                        f"block {block.role!r} ({which}) contains {forbidden.phrase!r}: "
                        f"{forbidden.why}. This is legal-adjacent output and the product has no "
                        f"standing to say it. The phrase list is config/forbidden-phrases.csv; "
                        f"if the phrase is genuinely acceptable, that is a data edit and a "
                        f"decision somebody signs their name to."
                    )
    return (
        f"scanned {checked} rendering(s) of {len(draft.blocks)} block(s) against "
        f"{len(library.forbidden)} forbidden phrase(s): none present"
    )


# -- rendering -------------------------------------------------------------


def _structural_values(intake: Intake, library: Library) -> dict[str, str]:
    """Values that are identical in the blank form and in the filled draft.

    They are structure or they are the type's own language: which POA type this
    is, which jurisdiction, both notices, and every clause number. Uploading
    them means the blank form is already a durable-POA-for-this-jurisdiction
    form, and no edit ever has to change one.
    """
    poa_type = library.types[intake.poa_type]
    jurisdiction = library.jurisdictions[intake.jurisdiction]
    return {
        "poa_type_label": poa_type.label,
        "durability_language": poa_type.durability_language,
        "jurisdiction_label": jurisdiction.label,
        "governing_law": jurisdiction.governing_law,
        "witness_requirement": jurisdiction.witness_requirement,
        "notarisation_requirement": jurisdiction.notarisation_requirement,
    }


def _instance_values(intake: Intake) -> dict[str, str]:
    return {
        "principal_name": intake.principal.name,
        "principal_address": intake.principal.address,
        "principal_id": intake.principal.identifier,
        "agent_name": intake.agent.name,
        "agent_address": intake.agent.address,
        "successor_name": intake.successor_agent.name,
        "successor_address": intake.successor_agent.address,
        "limitation": intake.limitation,
        "effective_date": intake.effective_date,
        "real_property_description": intake.real_property_description,
    }


def _render(
    clause: Clause,
    values: dict[str, str],
    numbering: dict[str, int],
    library: Library,
    intake: Intake,
    *,
    filled: bool,
) -> str:
    def substitute(match: re.Match[str]) -> str:
        name, argument = match.group(1), match.group(2)
        if name == "notice":
            return library.notices[argument].text
        if name == "clause_ref":
            if argument not in numbering:
                raise CrossReferenceError(
                    f"clause {clause.clause_id!r} refers to clause {argument!r}, which this "
                    f"draft does not select. A reference to a clause that is not in the "
                    f"document is never rendered as prose and never dropped."
                )
            return str(numbering[argument])
        if name == "powers":
            return _powers_list(argument, library, intake, values, filled=filled)
        if name == "signature_table":
            return _signature_table(library, values)
        if name not in values:
            raise UnresolvedPlaceholderError(
                f"clause {clause.clause_id!r} uses placeholder {{{name}}}, which has no "
                f"resolver. Known: {sorted(values)}. "
                f"An unresolved placeholder is never left in the document and never emptied - "
                f"a clause reading 'of  , born' is a draft that went out wrong quietly."
            )
        return str(values[name])

    inner = PLACEHOLDER.sub(substitute, clause.body)
    if clause.tag == "ul" or clause.tag == "table":
        # The list items and the table rows are already complete elements.
        return f'<{clause.tag} style="{style.BY_ROLE[clause.style_role]}">{inner}</{clause.tag}>'
    return style.wrap(clause.tag, clause.style_role, inner)


def _powers_list(
    category: str, library: Library, intake: Intake, values: dict, *, filled: bool
) -> str:
    if not filled:
        return f'<li style="{style.ITEM}">{values["powers"]}</li>'
    items = []
    for power_id in intake.powers_in(library, category):
        power = library.powers[power_id]
        # The whole sentence is the catalogue's, not ours: the label and the
        # language are both data, and nothing here writes prose about a power.
        items.append(
            f'<li style="{style.ITEM}"><strong>{power.label}.</strong> {power.language}</li>'
        )
    return "".join(items)


def _signature_table(library: Library, values: dict[str, str]) -> str:
    head = "".join(
        f'<th style="{style.TH}">{c.column_label}</th>' for c in library.signature_columns
    )
    rows = [f'<tr style="{style.HEAD_ROW}">{head}</tr>']
    for row in library.signature_rows:
        cells = []
        for column in library.signature_columns:
            if column.blank:
                # Empty, and it stays empty, in both fills and after every edit.
                # INVARIANTS.md A3: this product never implies a signature or a
                # notarisation happened, and the cheapest way to never imply it
                # is to have nowhere to put one.
                cells.append(f'<td style="{style.TD_BLANK}"></td>')
            elif column.fill == "label":
                cells.append(f'<td style="{style.TD}">{row.role_label}</td>')
            else:
                cells.append(
                    f'<td style="{style.TD}">{_fill_name(row.name_placeholder, values)}</td>'
                )
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return "".join(rows)


def _fill_name(placeholder: str, values: dict[str, str]) -> str:
    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in values:
            raise UnresolvedPlaceholderError(
                f"config/signature-rows.csv uses placeholder {{{name}}}, which has no resolver. "
                f"Known: {sorted(values)}. A signature block naming nobody is not a blank to be "
                f"filled in later; it is a row that lost its party."
            )
        return values[name]

    return PLACEHOLDER.sub(substitute, placeholder)
