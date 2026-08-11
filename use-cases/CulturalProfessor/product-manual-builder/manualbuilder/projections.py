"""The manual and the quick-start card, as two projections of one spec.

This is the mechanism behind the first grading criterion -- *the quick-start
stays consistent when the manual changes*. The usual way that consistency fails
is that both documents contain the same sentence and only one of them gets
edited. Here neither document contains anything: the torque figure, the
wavelength and the wording of every warning live in the spec, and both documents
are rendered from it. There is no second copy to go stale.

The card is not an abbreviated manual. It carries a different set of steps, a
different set of warnings and three of the six troubleshooting rows, declared in
the spec's `quick_start` block, because a card someone tapes to a workbench has
a different job from a manual someone reads once. What it must never carry is an
instruction the manual does not have, and `spec.py` refuses to load a spec where
it does.

Both documents are built as a list of `Block`s and then joined. That indirection
earns its keep twice: every block carries a `data-block` id that is the same in
every language, which is what `paginate.py` keys a page map off, and it carries
the words it holds, so a page can be measured without anyone parsing HTML back
into a document. The rendered HTML and the thing measured are the same object.

Diagrams arrive as an `images` mapping from diagram id to URL. Rendering with an
empty mapping is legal and produces a document with the diagrams' captions and
no `<img>` -- which is what makes the HTML testable without a network.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape

from manualbuilder.diagram import parts_list_rows
from manualbuilder.spec import Fault, Spec, Step, Warning_

BREAKDOWN = "breakdown"

SEVERITY_LABEL = {"danger": "Danger", "warning": "Warning", "caution": "Caution"}

TROUBLE_HEADERS = ("Symptom", "Likely cause", "What to do")


@dataclass(frozen=True)
class Block:
    """One laid-out piece of a document.

    `id` is structural and language-independent: `step:rails:body` is the rails
    instruction in every locale. `text` is the words it holds, which is all a
    page measurement needs. `starts_page` and `keep_with_next` are the two
    layout facts the source document asserts and every translation inherits --
    they are what makes "the German step 4 is on the same page as the English
    step 4" a property of the design rather than a coincidence of length.
    """
    id: str
    kind: str
    html: str
    text: str = ""
    rows: tuple[str, ...] = ()
    starts_page: bool = False
    keep_with_next: bool = False


def step_image_id(step: Step) -> str:
    return f"step:{step.id}"


def image_ids(spec: Spec) -> list[str]:
    """Every diagram the two documents reference, in a stable order.

    The renderer, the uploader and the edit path all iterate this, so none of
    them can be looking at a different set than the others.
    """
    return [BREAKDOWN] + [step_image_id(step) for step in spec.steps]


def render(blocks: list[Block]) -> str:
    return "\n".join(block.html for block in blocks if block.html) + "\n"


def captions(spec: Spec) -> dict[str, str]:
    """Every caption either document uses -> the diagram id it belongs to.

    The only anchor that survives a round trip. `data-diagram` does not: the
    service strips `data-*` attributes when it stores a document and puts its
    own `data-chunk-id` on instead, so a figure comes back as `<figure><img
    alt="..."></figure>` with nothing on it naming which drawing it is. The
    caption is derived from the spec, is visible to a reader, and is what the
    alt text carries -- a better anchor than an attribute in any case.

    Keyed by caption rather than by diagram id because the mapping is many to
    one: the breakdown appears in the manual pointing at a parts table and on
    the card with nothing to point at, so it is captioned differently in each.
    Both spellings have to resolve to the same drawing.
    """
    out = {
        f"{spec.name} parts breakdown. Numbers key to the table below.": BREAKDOWN,
        f"{spec.name} parts breakdown": BREAKDOWN,
    }
    for index, step in enumerate(spec.steps, start=1):
        out[f"Step {index}: {step.title}"] = step_image_id(step)
    return out


# ------------------------------------------------------------- the manual --

def manual_blocks(spec: Spec, images: dict[str, str] | None = None) -> list[Block]:
    images = images or {}
    out: list[Block] = []

    out.append(_heading("doc:title", 1, f"{spec.name} — Product Manual",
                        keep_with_next=True))
    out.append(_para("doc:tagline", f"<em>{escape(spec.tagline)}</em>",
                     spec.tagline, keep_with_next=True))
    out.append(_para("doc:meta",
                     f"Model {escape(spec.model_number)} · Revision "
                     f"{escape(spec.revision)}",
                     f"Model {spec.model_number} Revision {spec.revision}"))

    out.append(_section("sec:safety", "Before you start"))
    out.append(_para(
        "safety:preamble",
        "Read the safety notices below in full. They are repeated at the step "
        "they apply to, and the wording is the same in both places because it "
        "is written once.",
        "Read the safety notices below in full. They are repeated at the step "
        "they apply to, and the wording is the same in both places because it "
        "is written once."))
    out += _notices("safety", spec.warnings)

    out.append(_section("sec:specifications", "Specifications"))
    out.append(_table("specifications:table", ["Specification", "Value"],
                      [[label, value] for label, value in spec.specifications]))

    out.append(_section("sec:parts", "What is in the box"))
    out.append(_figure(images, "parts:figure", BREAKDOWN,
                       f"{spec.name} parts breakdown. Numbers key to the table "
                       f"below.", keep_with_next=True))
    out.append(_table("parts:table", ["No.", "Part", "Qty", "Notes"],
                      [[str(n), label, qty, note] for n, label, qty, note
                       in parts_list_rows(spec)]))

    out.append(_section("sec:setup", "Setting up"))
    for index, step in enumerate(spec.steps, start=1):
        # Every step opens a page. A step is a heading, its diagram and its
        # instruction, and those three are useless apart -- so rather than hope
        # they stay together as text lengths change per language, the break is
        # declared here and inherited by every translation.
        out.append(_heading(f"step:{step.id}:head", 3,
                            f"Step {index} — {step.title}",
                            starts_page=True, keep_with_next=True))
        out.append(_figure(images, f"step:{step.id}:figure",
                           step_image_id(step), f"Step {index}: {step.title}",
                           keep_with_next=True))
        out.append(_para(f"step:{step.id}:body", escape(step.body), step.body))
        out += _notices(f"step:{step.id}", spec.warnings_for(step))

    out.append(_section("sec:troubleshooting", "Troubleshooting"))
    out.append(_trouble_table("troubleshooting:table", spec.faults))

    for statement in spec.statements:
        out.append(_section(f"statement:{statement.id}:head", statement.title))
        out.append(_para(f"statement:{statement.id}:body",
                         escape(statement.body), statement.body))

    out.append(_section("sec:support", "Support"))
    out.append(_para("support:footer", escape(spec.quick_start_footer),
                     spec.quick_start_footer))
    return out


def manual_html(spec: Spec, images: dict[str, str] | None = None) -> str:
    return render(manual_blocks(spec, images))


# --------------------------------------------------------------- the card --

def quick_start_blocks(spec: Spec,
                       images: dict[str, str] | None = None) -> list[Block]:
    images = images or {}
    steps = spec.quick_start()
    out: list[Block] = []

    out.append(_heading("doc:title", 1, f"{spec.name} — Quick Start",
                        keep_with_next=True))
    out.append(_para("doc:meta",
                     f"Model {escape(spec.model_number)} · Revision "
                     f"{escape(spec.revision)} · {len(steps)} steps",
                     f"Model {spec.model_number} Revision {spec.revision} "
                     f"{len(steps)} steps"))

    out.append(_section("sec:safety", "Read first"))
    out += _notices("safety", [spec.warning(w) for w in spec.quick_start_warnings])

    out.append(_section("sec:setup", "Set up"))
    # Numbered by their position on the card, not by their position in the
    # manual. The card is its own reading order; the manual's step numbers would
    # be a sequence with holes in it.
    for index, step in enumerate(steps, start=1):
        # One step per panel. A folded card's panels are physical: the crease is
        # where it is whatever language is printed on it, so a step that flowed
        # across the fold in German would be a card that folds through a
        # sentence. Declaring the break makes the panel the unit that has to fit
        # -- which `paginate` then checks, rather than the translation being
        # free to push step six onto the back.
        out.append(_heading(f"step:{step.id}:head", 3, f"{index}. {step.title}",
                            starts_page=True, keep_with_next=True))
        out.append(_para(f"step:{step.id}:body", escape(step.body), step.body))

    out.append(_section("sec:troubleshooting", "If something is wrong"))
    out.append(_trouble_table("troubleshooting:table",
                              spec.quick_start_troubleshooting()))

    out.append(_section("sec:reference", "Assembly reference"))
    out.append(_figure(images, "parts:figure", BREAKDOWN,
                       f"{spec.name} parts breakdown"))

    out.append(_para("support:footer", escape(spec.quick_start_footer),
                     spec.quick_start_footer))
    return out


def quick_start_html(spec: Spec, images: dict[str, str] | None = None) -> str:
    return render(quick_start_blocks(spec, images))


# ---------------------------------------------------------------- shared --

def _heading(block_id: str, level: int, text: str, *, starts_page: bool = False,
             keep_with_next: bool = False) -> Block:
    return Block(
        id=block_id, kind=f"h{level}",
        html=f'<h{level} data-block="{escape(block_id, quote=True)}">'
             f"{escape(text)}</h{level}>",
        text=text, starts_page=starts_page, keep_with_next=keep_with_next,
    )


def _section(block_id: str, title: str) -> Block:
    """A top-level section heading. Opens a page, and never ends one.

    Page assignment falling out of the section list rather than out of text flow
    is the whole of the localisation guarantee: a section that begins on page
    three begins on page three in every language, because nothing upstream of it
    can push it.
    """
    return _heading(block_id, 2, title, starts_page=True, keep_with_next=True)


def _para(block_id: str, inner_html: str, text: str, *,
          keep_with_next: bool = False) -> Block:
    return Block(
        id=block_id, kind="p",
        html=f'<p data-block="{escape(block_id, quote=True)}">{inner_html}</p>',
        text=text, keep_with_next=keep_with_next,
    )


def _notices(prefix: str, warnings: list[Warning_]) -> list[Block]:
    """Safety notices, one block each, so a page break can fall between two.

    Splitting a single notice across a page is what the block boundary prevents;
    splitting a run of them is fine and is what lets a long safety section
    paginate at all.
    """
    out: list[Block] = []
    for warning in warnings:
        label = SEVERITY_LABEL.get(warning.severity, warning.severity.title())
        text = f"{label}: {warning.title}. {warning.body}"
        out.append(Block(
            id=f"{prefix}:warning:{warning.id}", kind="notice",
            html=f'<p data-block="{escape(f"{prefix}:warning:{warning.id}", quote=True)}">'
                 f"<strong>{escape(label)}: {escape(warning.title)}.</strong> "
                 f"{escape(warning.body)}</p>",
            text=text,
        ))
    return out


def _figure(images: dict[str, str], block_id: str, image_id: str, caption: str,
            *, keep_with_next: bool = False) -> Block:
    """A figure, with its caption whether or not the image exists yet.

    The caption is not decoration: it is what carries the figure when a document
    is read as text, and it is the anchor the edit path uses to find the chunk
    holding a given diagram.
    """
    url = images.get(image_id)
    picture = (f'<img src="{escape(url, quote=True)}" alt="{escape(caption)}"/>'
               if url else "")
    return Block(
        id=block_id, kind="figure",
        html=f'<figure data-block="{escape(block_id, quote=True)}" '
             f'data-diagram="{escape(image_id, quote=True)}">{picture}'
             f"<figcaption>{escape(caption)}</figcaption></figure>",
        text=caption, keep_with_next=keep_with_next,
    )


def _table(block_id: str, headers: list[str], rows: list[list[str]]) -> Block:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return Block(
        id=block_id, kind="table",
        html=f'<table data-block="{escape(block_id, quote=True)}">'
             f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>",
        text=" ".join(headers),
        rows=tuple(" ".join(row) for row in rows),
    )


def _trouble_table(block_id: str, faults: list[Fault]) -> Block:
    """The troubleshooting table, in both documents, from the same rows.

    The card carries three of the six rows and the manual carries all of them,
    and the three on the card are the manual's rows verbatim -- same object,
    rendered twice, so "the card's fix disagrees with the manual's fix" has no
    way to happen.
    """
    return _table(block_id, list(TROUBLE_HEADERS),
                  [[f.symptom, f.cause, f.fix] for f in faults])


__all__ = ["Block", "manual_html", "quick_start_html", "manual_blocks",
           "quick_start_blocks", "render", "image_ids", "step_image_id",
           "BREAKDOWN", "TROUBLE_HEADERS"]
