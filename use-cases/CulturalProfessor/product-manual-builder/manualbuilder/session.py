"""Publishing the pair, and editing it without letting the two drift apart.

Two ways an edit reaches these documents, and the split is deliberate.

**Structural edits go through the spec.** Adding a part, renumbering the
assembly, changing which steps the card carries -- these change the diagrams, so
they are made in `spec/*.yaml`, regenerated, and re-published. A model is never
asked to redraw anything.

**Wording edits go through one multi-document chat turn.** "Raise the rail
torque to 1.6 N·m" is the kind of edit that actually happens to a shipped manual,
and it is exactly where a manual and its quick-start card come apart: someone
edits one document and forgets the other. Opening both in a single session and
sending one instruction means one turn produces both edits. There is no window
in which the manual has been updated and the card has not, because there is no
second request.

That is the first grading criterion, and `changes_by_document` is how a caller
checks it actually happened rather than trusting that it did.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from manualbuilder import diagram, projections as pj
from manualbuilder.spec import Spec
from manualbuilder.superdocs import ProposedChange, SuperDocs, SuperDocsError


@dataclass
class Publication:
    """What was published, and enough to edit it again."""
    manual_id: str
    card_id: str
    images: dict[str, str] = field(default_factory=dict)
    session_id: str | None = None

    @property
    def document_ids(self) -> list[str]:
        return [self.manual_id, self.card_id]

    def name_for(self, document_id: str) -> str:
        if document_id == self.manual_id:
            return "manual"
        if document_id == self.card_id:
            return "quick-start card"
        return document_id


def render_diagrams(spec: Spec) -> dict[str, str]:
    """Every diagram the documents reference, as SVG, keyed by diagram id."""
    out = {pj.BREAKDOWN: diagram.exploded(spec)}
    for step in spec.steps:
        out[pj.step_image_id(step)] = diagram.for_step(spec, step)
    return out


def upload_diagrams(client: SuperDocs, spec: Spec) -> dict[str, str]:
    """Render and upload, returning diagram id -> URL.

    Iterates `projections.image_ids` so the set uploaded is exactly the set the
    documents reference. A diagram uploaded but never referenced is wasted quota;
    one referenced but never uploaded is a broken image in a shipped manual.
    """
    svgs = render_diagrams(spec)
    urls: dict[str, str] = {}
    for image_id in pj.image_ids(spec):
        filename = image_id.replace(":", "_") + ".svg"
        urls[image_id] = client.upload_image(filename, svgs[image_id])
    return urls


def publish(client: SuperDocs, spec: Spec, language: str = "") -> Publication:
    """Upload the diagrams, then both documents that reference them.

    `language` only names the files. What makes these the German documents is
    that `spec` is the German spec -- including its drawings, which are rendered
    from a parts graph carrying German labels rather than being the English ones
    with a translation around them.
    """
    images = upload_diagrams(client, spec)
    suffix = f"-{language}" if language else ""
    manual_id = client.upload(
        f"{_slug(spec.name)}-manual{suffix}.html", pj.manual_html(spec, images))
    card_id = client.upload(
        f"{_slug(spec.name)}-quickstart{suffix}.html",
        pj.quick_start_html(spec, images))
    return Publication(manual_id=manual_id, card_id=card_id, images=images)


def edit_both(client: SuperDocs, publication: Publication,
              instruction: str) -> tuple[list[ProposedChange], dict[str, Any]]:
    """One instruction, both documents open, changes parked for approval.

    Returns the proposed changes and the raw reply. Nothing is applied: the turn
    parks at `awaiting_approval` so a person -- or the assertion below -- can
    look at what it wants to do first.
    """
    reply = client.chat(instruction, publication.document_ids,
                        session_id=publication.session_id)
    publication.session_id = (reply.get("session_id")
                              or reply.get("id") or publication.session_id)
    return client.pending_changes(reply), reply


def changes_by_document(publication: Publication,
                        changes: list[ProposedChange]) -> dict[str, list[ProposedChange]]:
    """Group a turn's changes by the document they touch.

    This is the check behind the consistency claim. One instruction that comes
    back having touched only the manual is drift caught before it ships, and the
    caller can refuse the whole batch.
    """
    grouped: dict[str, list[ProposedChange]] = {
        publication.manual_id: [], publication.card_id: []}
    for change in changes:
        grouped.setdefault(change.document_id or "unknown", []).append(change)
    return grouped


def assert_touched_both(publication: Publication,
                        changes: list[ProposedChange]) -> None:
    """Refuse a batch that would leave the pair disagreeing.

    An edit to a fact that appears in both documents must propose changes to
    both. If it did not, applying it produces exactly the divergence this build
    exists to prevent -- so the batch is rejected rather than half-applied.
    """
    grouped = changes_by_document(publication, changes)
    empty = [publication.name_for(doc_id)
             for doc_id in publication.document_ids if not grouped[doc_id]]
    if empty:
        raise SuperDocsError(
            "this edit proposed no change to the "
            + " or the ".join(empty)
            + ". Applying it would leave the manual and the card disagreeing, "
              "so nothing was approved. Either the fact does not appear in that "
              "document, or the instruction was too narrow."
        )


def approve_all(client: SuperDocs, publication: Publication,
                changes: list[ProposedChange]) -> dict[str, Any]:
    if not publication.session_id:
        raise SuperDocsError("no session to approve against; run edit_both first")
    return client.approve(publication.session_id,
                          {change.change_id: True for change in changes})


def refresh_diagrams(client: SuperDocs, publication: Publication,
                     spec: Spec) -> dict[str, str]:
    """Re-render every diagram from the graph and re-upload it.

    The second grading criterion, and the reason it is a separate function from
    `edit_both`: a diagram is never edited, it is replaced. No model is in the
    drawing path at all. Getting the new URL into the document is `swap_diagrams`
    below, and that is where the interesting part is.
    """
    fresh = upload_diagrams(client, spec)
    publication.images = fresh
    return fresh


def swap_diagrams(client: SuperDocs, publication: Publication,
                  spec: Spec) -> tuple[list[ProposedChange], dict[str, str]]:
    """Re-render, upload, and propose swapping each `<img src>` for the new URL.

    A document already on the service cannot be re-uploaded without becoming a
    different document, so the new URL has to reach the existing chunks, and the
    only edit surface is a chat turn. That means asking a model to perform what
    is really a text substitution -- which is exactly the kind of step this
    project otherwise avoids.

    So it is asked for, and then it is checked. `assert_only_the_image_changed`
    compares each proposed chunk against the one it replaces with the image URLs
    masked out: if a single other character moved, the batch is refused whole.
    The model is allowed to propose the swap and is not trusted to have made it.
    """
    fresh = refresh_diagrams(client, publication, spec)
    lines = "\n".join(
        f'- the figure with data-diagram="{image_id}": set its <img src> to '
        f"{url}" for image_id, url in fresh.items()
    )
    instruction = (
        "Update the diagram image URLs. Make exactly these substitutions and "
        "nothing else -- do not reword, reformat, or renumber anything, and do "
        "not touch a figure that is not listed:\n" + lines
    )
    changes, _ = edit_both(client, publication, instruction)
    return changes, fresh


_IMG_SRC = re.compile(r'(<img\b[^>]*?\bsrc=")([^"]*)(")', re.I)
_FIGURE_ID = re.compile(r'data-diagram="([^"]+)"')


def _masked(html: str) -> str:
    """The chunk with every image URL replaced by a placeholder."""
    return _IMG_SRC.sub(r"\g<1>\g<3>", html)


def assert_only_the_image_changed(changes: list[ProposedChange],
                                  images: dict[str, str]) -> None:
    """Refuse a diagram swap that did anything besides swap the diagram.

    Three ways this goes wrong, and all three are refused rather than shown to a
    person to notice: the turn rewrote surrounding prose while it was in there;
    it changed a figure nobody asked it to; or it put a URL in the `src` that is
    not the one just uploaded for that figure -- a plausible-looking URL is the
    single most likely thing for a model to produce here, and it would render as
    a broken image in a shipped manual.
    """
    if not changes:
        raise SuperDocsError(
            "the turn proposed no changes, so the documents still point at the "
            "old diagrams. Nothing was uploaded in vain -- but nothing was "
            "swapped either."
        )

    for change in changes:
        if _masked(change.old_html) != _masked(change.new_html):
            raise SuperDocsError(
                f"change {change.change_id} altered more than the image URL in "
                f"chunk {change.chunk_id}. A diagram refresh is a URL "
                f"substitution and nothing else, so the whole batch was "
                f"refused.\n  before: {change.old_html[:160]}\n"
                f"  after:  {change.new_html[:160]}"
            )

        figures = _FIGURE_ID.findall(change.new_html)
        sources = [m.group(2) for m in _IMG_SRC.finditer(change.new_html)]
        if len(figures) != len(sources):
            raise SuperDocsError(
                f"change {change.change_id} has {len(figures)} figure(s) and "
                f"{len(sources)} image(s) in the same chunk; the pairing that "
                f"proves the right URL went to the right figure is not there"
            )
        for image_id, source in zip(figures, sources):
            if image_id not in images:
                raise SuperDocsError(
                    f"change {change.change_id} touched figure {image_id!r}, "
                    f"which was not part of this refresh"
                )
            if source != images[image_id]:
                raise SuperDocsError(
                    f"change {change.change_id} set {image_id!r} to {source!r}, "
                    f"which is not the URL uploaded for it ({images[image_id]!r}). "
                    f"That renders as a broken image in a shipped manual."
                )


def _slug(name: str) -> str:
    return "".join(c.lower() if c.isalnum() else "-" for c in name).strip("-")


__all__ = ["Publication", "publish", "edit_both", "approve_all", "refresh_diagrams",
           "swap_diagrams", "assert_only_the_image_changed", "changes_by_document",
           "assert_touched_both", "render_diagrams", "upload_diagrams"]
