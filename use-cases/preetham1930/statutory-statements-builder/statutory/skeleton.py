"""The whole document, computed here, in both its shapes.

Decision 29, stated as code: we compute the **entire** final skeleton - every
heading at its final number, every cross-reference already repointed, the new
note's heading already in place - and upload that verbatim. There is no
insertion to perform, so the insertion bug cannot be reached; SuperDocs only
ever replaces the contents of a chunk that already exists.

Two renderings come out of one structure:

- `skeleton` - the document as uploaded. Same structure, last year's figures.
- `target`   - the document we intend to end up with.

The edit plan is exactly the blocks where the two differ, and **no heading block
is ever one of them** (INVARIANTS.md item 2). Blocks that are identical need no
edit and are never sent, which is what makes this a focused update rather than a
full rewrite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from . import style
from .bodies import BodyBuilder, Element, NoteContent
from .chunks import tidy
from .errors import CrossReferenceError
from .figures import AnyFigure, Body, Cite
from .money import money_tokens_in_html
from .notetree import NoteTree
from .priorset import NOTE_REFERENCE
from .statements import Line, RollForward, Statement


@dataclass
class Block:
    """One top-level element, which becomes one chunk on upload."""

    role: str
    tag: str
    skeleton: str
    target: str
    note_number: int | None = None
    figures: tuple[AnyFigure, ...] = ()
    quotes: tuple[Cite, ...] = ()
    editable: bool = True  # headings are structure and are never targeted

    def __post_init__(self) -> None:
        object.__setattr__(self, "skeleton", tidy(self.skeleton))
        object.__setattr__(self, "target", tidy(self.target))

    @property
    def changed(self) -> bool:
        return self.skeleton != self.target


@dataclass
class StatutoryDocument:
    blocks: list[Block] = field(default_factory=list)
    notes: list[NoteContent] = field(default_factory=list)
    tree: NoteTree | None = None
    coverage: dict[str, int] = field(default_factory=dict)

    def html(self, which: str = "target") -> str:
        return "\n".join(getattr(b, which) for b in self.blocks)

    @property
    def figures(self) -> tuple[AnyFigure, ...]:
        return tuple(f for b in self.blocks for f in b.figures)

    @property
    def cites(self) -> tuple[Cite, ...]:
        out = [c for f in self.figures for c in f.cites]
        out.extend(c for b in self.blocks for c in b.quotes)
        out.extend(c for n in self.notes for d in n.disagreements for s in d.sides for c in s.cites)
        return tuple(out)

    def editable_changed(self) -> list[Block]:
        return [b for b in self.blocks if b.editable and b.changed]


def build_document(
    rolled: RollForward,
    tree: NoteTree,
    mapping: dict[str, int | None],
    corpus_root: Path,
    config_root: Path,
) -> StatutoryDocument:
    prior = rolled.prior
    document = StatutoryDocument(tree=tree)
    year = rolled.year
    prior_year = rolled.prior_year

    # -- header ------------------------------------------------------------
    document.blocks.append(
        Block("entity", "h1", prior.header[0].raw, prior.header[0].raw, editable=False)
    )
    document.blocks.append(
        Block("registered-office", "p", prior.header[1].raw, prior.header[1].raw, editable=False)
    )
    # The basis-of-preparation block is the signed set's own paragraph with the
    # year moved on. Retyping it here would put the standard's name into our
    # source, and a build that knows the name of the standard has started to
    # remember the domain instead of reading it (there is a test).
    basis_prior = prior.header[2].raw
    basis_target = basis_prior.replace(f"31 March {prior_year}", f"31 March {year}")
    if basis_target == basis_prior:
        raise CrossReferenceError(
            f"the signed set's basis-of-preparation paragraph does not name "
            f"'31 March {prior_year}', so the reporting date cannot be rolled forward from it: "
            f"{basis_prior[:160]}"
        )
    document.blocks.append(Block("basis-of-preparation", "p", basis_prior, basis_target))
    document.blocks.append(
        Block(
            "status",
            "p",
            prior.header[3].raw,
            "<p><em>Draft prepared by roll-forward for review. Not approved and not signed.</em></p>",
        )
    )

    # -- primary statements ------------------------------------------------
    for statement in rolled.statements:
        heading = f"<h2>{statement.title} 31 March {year}</h2>"
        document.blocks.append(
            Block(f"{statement.key}-heading", "h2", heading, heading, editable=False)
        )
        skeleton_html, target_html, figures = _render_statement(statement, rolled, prior)
        document.blocks.append(
            Block(statement.key, "table", skeleton_html, target_html, figures=figures)
        )

    notes_heading = "<h2>Notes to the Financial Statements</h2>"
    document.blocks.append(
        Block("notes-heading", "h2", notes_heading, notes_heading, editable=False)
    )

    # -- notes -------------------------------------------------------------
    builder = BodyBuilder(rolled, tree, mapping, corpus_root, config_root)
    for note in tree.notes:
        heading = f"<h3>Note {note.number} &mdash; {note.title}</h3>"
        document.blocks.append(
            Block("note-heading", "h3", heading, heading, note_number=note.number, editable=False)
        )
        content = builder.build(note)
        document.notes.append(content)
        for element in content.elements:
            document.blocks.append(
                Block(
                    f"note-{note.number}-{element.role}",
                    element.tag,
                    element.skeleton,
                    element.target,
                    note_number=note.number,
                    figures=element.figures,
                    quotes=element.quotes,
                )
            )
    document.coverage = dict(builder.coverage)
    _assert_cross_references_resolve(document, tree)
    return document


def _render_statement(
    statement: Statement, rolled: RollForward, prior
) -> tuple[str, str, tuple[AnyFigure, ...]]:
    year, prior_year = rolled.year, rolled.prior_year
    body = Body().markup(
        f'{style.table_open()}\n<tr style="{style.HEAD_ROW}">'
        f"{style.head_cell('Particulars')}{style.head_cell('Note', numeric=True)}"
        f'<th style="{style.TH_NUM}">'
    )
    body.dated(f"31 March {year}", f"31 March {prior_year}").markup(
        f'</th><th style="{style.TH_NUM}">'
    )
    body.dated(f"31 March {prior_year}", f"31 March {prior_year - 1}").markup("</th></tr>\n")
    for line in statement.lines:
        if line.kind in ("section", "subheader"):
            wrap = ("<strong>", "</strong>") if line.kind == "section" else ("<em>", "</em>")
            body.markup(
                f'<tr style="{style.SECTION_ROW}"><td colspan="4" style="{style.TD_TEXT}">{wrap[0]}'
            ).text(line.caption).markup(f"{wrap[1]}</td></tr>\n")
            continue
        open_tag, close_tag = ("<strong>", "</strong>") if line.emphasis else ("", "")
        body.markup(f'<tr><td style="{style.TD_TEXT}">').markup(open_tag).text(line.caption).markup(
            close_tag
        )
        body.markup(f'</td><td style="{style.TD_NUM}">')
        if line.note_ref is not None:
            body.text(str(line.note_ref))
        body.markup(f'</td><td style="{style.TD_NUM}">').markup(open_tag)
        body.fig(line.current, line.prior)
        body.markup(f'{close_tag}</td><td style="{style.TD_NUM}">{open_tag}')
        body.fig(line.prior, _signed_prior_prior(prior, line))
        body.markup(f"{close_tag}</td></tr>\n")
    body.markup("</table>")
    where = f"{statement.key} table"
    return body.skeleton(where), body.render(where), body.figures


def _signed_prior_prior(prior, line: Line) -> str:
    """The signed set's own second column, used only as skeleton scaffolding."""
    found = prior.statement_row(line.caption)
    if found is not None and len(found[1].values) > 1:
        return found[1].values[1]
    return "0.00"


def _assert_cross_references_resolve(document: StatutoryDocument, tree: NoteTree) -> None:
    """Every `Note N` anywhere in the final document names a heading that exists."""
    numbers = {note.number for note in tree.notes}
    for block in document.blocks:
        if block.role == "note-heading":
            continue
        for match in NOTE_REFERENCE.finditer(block.target):
            referenced = int(match.group(1))
            if referenced not in numbers:
                raise CrossReferenceError(
                    f"block {block.role!r} points at Note {referenced}, which the final "
                    f"document does not have. Notes run 1..{max(numbers)}. Every reference is "
                    f"repointed through the same map that renumbered the headings, so this is "
                    f"a bug in the map, not a caveat."
                )
    for statement in ("balance_sheet", "profit_and_loss"):
        block = next(b for b in document.blocks if b.role == statement)
        del block


def assert_note_captions_tie(document: StatutoryDocument, rolled: RollForward) -> list[str]:
    """Every figure a note states for a caption is the figure the statement prints.

    Checked on the **rendered HTML** rather than on the objects, because the
    objects being shared is the reason it holds and the rendering is what a
    reader sees. Returns one line per checked caption for the run summary.
    """
    checked: list[str] = []
    for statement in rolled.statements:
        table = next(b for b in document.blocks if b.role == statement.key)
        table_tokens = money_tokens_in_html(table.target)
        for line in statement.lines:
            if line.account is None or line.note_ref is None:
                continue
            note_blocks = [
                b
                for b in document.blocks
                if b.note_number == line.note_ref and b.role.endswith("captions")
            ]
            if not note_blocks:
                continue
            note_tokens = money_tokens_in_html(note_blocks[0].target)
            current = line.current.rendered
            if current not in table_tokens:
                raise CrossReferenceError(f"{line.caption}: the statement does not print {current}")
            if current not in note_tokens:
                raise CrossReferenceError(
                    f"{line.caption}: Note {line.note_ref} does not print {current}, which the "
                    f"statement does. The note and the primary statement must tie exactly."
                )
            checked.append(f"{line.caption} -> Note {line.note_ref}: {current}")
    return checked


def zero() -> Decimal:  # pragma: no cover - keeps Decimal imported for callers
    return Decimal(0)


def note_body_blocks(document: StatutoryDocument, number: int) -> list[Block]:
    return [b for b in document.blocks if b.note_number == number and b.role != "note-heading"]


def elements_of(content: NoteContent) -> list[Element]:  # pragma: no cover - convenience
    return content.elements
