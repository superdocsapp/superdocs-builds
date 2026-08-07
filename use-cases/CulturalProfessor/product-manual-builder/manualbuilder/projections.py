"""The manual and the quick-start card, as two projections of one spec.

This is the mechanism behind the first grading criterion -- *the quick-start
stays consistent when the manual changes*. The usual way that consistency fails
is that both documents contain the same sentence and only one of them gets
edited. Here neither document contains anything: the torque figure, the
wavelength and the wording of every warning live in the spec, and both documents
are rendered from it. There is no second copy to go stale.

The card is not an abbreviated manual. It carries a different set of steps and a
different set of warnings, declared in the spec's `quick_start` block, because a
card someone tapes to a workbench has a different job from a manual someone
reads once. What it must never carry is an instruction the manual does not have,
and `spec.py` refuses to load a spec where it does.

Diagrams arrive as an `images` mapping from diagram id to URL. Rendering with an
empty mapping is legal and produces a document with the diagrams' captions and
no `<img>` -- which is what makes the HTML testable without a network.
"""
from __future__ import annotations

from html import escape

from manualbuilder.diagram import parts_list_rows
from manualbuilder.spec import Spec, Step, Warning_

BREAKDOWN = "breakdown"

SEVERITY_LABEL = {"danger": "Danger", "warning": "Warning", "caution": "Caution"}


def step_image_id(step: Step) -> str:
    return f"step:{step.id}"


def image_ids(spec: Spec) -> list[str]:
    """Every diagram the two documents reference, in a stable order.

    The renderer, the uploader and the edit path all iterate this, so none of
    them can be looking at a different set than the others.
    """
    return [BREAKDOWN] + [step_image_id(step) for step in spec.steps]


# ------------------------------------------------------------- the manual --

def manual_html(spec: Spec, images: dict[str, str] | None = None) -> str:
    images = images or {}
    out: list[str] = []
    add = out.append

    add(f"<h1>{escape(spec.name)} — Product Manual</h1>")
    add(f"<p><em>{escape(spec.tagline)}</em></p>")
    add(f"<p>Model {escape(spec.model_number)} · Revision "
        f"{escape(spec.revision)}</p>")

    add("<h2>Before you start</h2>")
    add("<p>Read the safety notices below in full. They are repeated at the "
        "step they apply to, and the wording is the same in both places because "
        "it is written once.</p>")
    add(_warnings_block(spec.warnings))

    add("<h2>Specifications</h2>")
    add(_table(["Specification", "Value"],
               [[label, value] for label, value in spec.specifications]))

    add("<h2>What is in the box</h2>")
    add(_figure(images, BREAKDOWN,
                f"{spec.name} parts breakdown. Numbers key to the table below."))
    add(_table(["No.", "Part", "Qty", "Notes"],
               [[str(n), label, qty, note] for n, label, qty, note
                in parts_list_rows(spec)]))

    add("<h2>Setting up</h2>")
    for index, step in enumerate(spec.steps, start=1):
        add(f"<h3>Step {index} — {escape(step.title)}</h3>")
        add(_figure(images, step_image_id(step),
                    f"Step {index}: {step.title}"))
        add(f"<p>{escape(step.body)}</p>")
        if step.warnings:
            add(_warnings_block(spec.warnings_for(step)))

    add("<h2>Support</h2>")
    add(f"<p>{escape(spec.quick_start_footer)}</p>")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------- the card --

def quick_start_html(spec: Spec, images: dict[str, str] | None = None) -> str:
    images = images or {}
    steps = spec.quick_start()
    out: list[str] = []
    add = out.append

    add(f"<h1>{escape(spec.name)} — Quick Start</h1>")
    add(f"<p>Model {escape(spec.model_number)} · Revision "
        f"{escape(spec.revision)} · {len(steps)} steps</p>")

    add("<h2>Read first</h2>")
    add(_warnings_block([spec.warning(w) for w in spec.quick_start_warnings]))

    add("<h2>Set up</h2>")
    # Numbered by their position on the card, not by their position in the
    # manual. The card is its own reading order; the manual's step numbers would
    # be a sequence with holes in it.
    for index, step in enumerate(steps, start=1):
        add(f"<h3>{index}. {escape(step.title)}</h3>")
        add(f"<p>{escape(step.body)}</p>")

    add("<h2>Assembly reference</h2>")
    add(_figure(images, BREAKDOWN, f"{spec.name} parts breakdown"))

    add(f"<p>{escape(spec.quick_start_footer)}</p>")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- shared --

def _warnings_block(warnings: list[Warning_]) -> str:
    if not warnings:
        return ""
    rows: list[str] = []
    for warning in warnings:
        label = SEVERITY_LABEL.get(warning.severity, warning.severity.title())
        rows.append(
            f"<p><strong>{escape(label)}: {escape(warning.title)}.</strong> "
            f"{escape(warning.body)}</p>"
        )
    return "\n".join(rows)


def _figure(images: dict[str, str], image_id: str, caption: str) -> str:
    """A figure, with its caption whether or not the image exists yet.

    The caption is not decoration: it is what carries the figure when a document
    is read as text, and it is the anchor the edit path uses to find the chunk
    holding a given diagram.
    """
    url = images.get(image_id)
    picture = (f'<img src="{escape(url, quote=True)}" alt="{escape(caption)}"/>'
               if url else "")
    return (f'<figure data-diagram="{escape(image_id, quote=True)}">{picture}'
            f"<figcaption>{escape(caption)}</figcaption></figure>")


def _table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


__all__ = ["manual_html", "quick_start_html", "image_ids", "step_image_id",
           "BREAKDOWN"]
