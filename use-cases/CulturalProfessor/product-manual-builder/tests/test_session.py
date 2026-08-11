"""What the two documents refuse to have done to them.

`session.py` is where the product decisions live, and both of them are refusals:
an edit that would leave the manual and the card disagreeing, and a diagram
refresh that turned out to be more than a diagram refresh.

The second one is the interesting one. A document already on the service cannot
be re-uploaded without becoming a different document, so a new diagram URL has
to reach the existing chunks, and the only edit surface is a chat turn -- which
means asking a model to perform a text substitution. That is exactly the kind of
step this project otherwise avoids, so it is asked for and then checked, and the
checking is what these tests are about. Every one of them is a batch that looks
plausible and is refused.

No network: a proposed change is a dataclass, and that is all these need.
"""
from __future__ import annotations

import pytest

from manualbuilder import session
from manualbuilder.superdocs import ProposedChange, SuperDocsError

#: Keyed by caption, because that is the only anchor that survives an upload:
#: the service strips `data-*` and hands the figure back as
#: `<figure><img alt="..."></figure>`.
IMAGES = {
    "Halyard M1 parts breakdown": "https://cdn.example/breakdown-v2.svg",
    "Step 4: Fit the laser module": "https://cdn.example/step_laser-v2.svg",
}
LASER = "Step 4: Fit the laser module"


def figure(caption: str, url: str, extra: str = "", chunked: bool = False) -> str:
    """A figure as this renderer writes it, or as the service hands it back.

    `chunked=True` is the shape that comes back: `data-*` gone, a `data-chunk-id`
    added, and `alt` before `src` rather than after. A check that only worked on
    the shape we sent would pass every test and fail on the first real chunk.
    """
    if chunked:
        return (f'<figure data-chunk-id="f248c6f2"><img alt="{caption}" '
                f'src="{url}"/><figcaption>{caption}</figcaption></figure>{extra}')
    return (f'<figure data-block="step:laser:figure" data-diagram="step:laser">'
            f'<img src="{url}" alt="{caption}"/>'
            f"<figcaption>{caption}</figcaption></figure>{extra}")


def swap(new_html: str, old_html: str | None = None,
         change_id: str = "c1") -> ProposedChange:
    return ProposedChange(
        change_id=change_id, operation="edit", chunk_id="chunk_12",
        document_id="doc_manual",
        old_html=old_html if old_html is not None else figure(
            LASER, "https://cdn.example/step_laser-v1.svg"),
        new_html=new_html, explanation="updated the diagram",
    )


def test_the_swap_that_is_only_a_swap_is_allowed():
    changes = [swap(figure(LASER, IMAGES[LASER]))]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_the_shape_the_service_actually_returns_is_allowed():
    """The same swap, in the markup a real chunk comes back as: attributes
    stripped, a chunk id added, alt before src. The first live run refused this
    because the check was reading the markup we sent rather than the markup that
    came back."""
    changes = [swap(
        new_html=figure(LASER, IMAGES[LASER], chunked=True),
        old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg",
                        chunked=True))]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_a_reworded_caption_is_refused():
    """The likeliest failure, and the most reasonable-looking one: asked to
    change a URL, the turn tidies the caption while it is in there. A person
    reviewing forty of these approves it."""
    changes = [swap(figure("Step 4: Fitting the laser module", IMAGES[LASER]))]
    with pytest.raises(SuperDocsError, match="altered more than the image URL"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_paragraph_added_next_to_the_figure_is_refused():
    changes = [swap(figure(LASER, IMAGES[LASER],
                           extra="<p>See also the parts table.</p>"))]
    with pytest.raises(SuperDocsError, match="altered more than the image URL"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_plausible_url_that_was_never_uploaded_is_refused():
    """The single most likely thing for a model to produce here: a URL that
    looks exactly right. It renders as a broken image in a shipped manual, and
    it is the reason this check compares against what was uploaded rather than
    checking that the src merely changed."""
    invented = "https://cdn.example/step_laser-v3.svg"
    changes = [swap(figure(LASER, invented))]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_the_right_url_on_the_wrong_figure_is_refused():
    """Both URLs are real and both were uploaded in this refresh. They are on
    the wrong figures, so every page still shows a diagram and two of them are
    the wrong drawing -- which is the failure a person is least likely to catch
    by reading a diff."""
    changes = [swap(figure(LASER, IMAGES["Halyard M1 parts breakdown"]))]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_figure_nobody_asked_about_is_refused():
    changes = [swap(
        new_html=figure("Step 6: Power up and home",
                        "https://cdn.example/step_power-v2.svg"),
        old_html=figure("Step 6: Power up and home",
                        "https://cdn.example/step_power-v1.svg"))]
    with pytest.raises(SuperDocsError, match="not part of this refresh"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_an_image_with_no_caption_to_identify_it_is_refused():
    """A figure whose alt text was dropped cannot be checked: there is nothing
    left saying which drawing it is meant to be. A check that cannot be made is
    reported, not skipped."""
    anonymous = '<figure><img src="https://cdn.example/step_laser-v2.svg"/></figure>'
    changes = [swap(new_html=anonymous,
                    old_html=anonymous.replace("-v2", "-v1"))]
    with pytest.raises(SuperDocsError, match="not part of this refresh"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_an_empty_batch_is_not_a_success():
    """A turn that proposed nothing leaves the documents pointing at the old
    diagrams, and a `sync` that printed ok would be claiming otherwise."""
    with pytest.raises(SuperDocsError, match="proposed no changes"):
        session.assert_only_the_image_changed([], IMAGES)


def test_one_bad_change_refuses_the_whole_batch():
    """Not "approve the good ones and flag the rest". If one chunk came back
    rewritten, what the turn did to the others is not evidence of anything."""
    changes = [
        swap(figure("Halyard M1 parts breakdown",
                    IMAGES["Halyard M1 parts breakdown"]), change_id="ok"),
        swap(figure("Reworded", IMAGES[LASER]), change_id="bad"),
    ]
    with pytest.raises(SuperDocsError, match="whole batch was refused"):
        session.assert_only_the_image_changed(changes, IMAGES)


# ------------------------------------- the figure that was left behind --

#: What each document was asked to swap: the manual holds both figures, the card
#: holds only the breakdown, and it captions it differently.
ASKED = {
    "doc_manual": {"Halyard M1 parts breakdown. Numbers key to the table below.":
                   "breakdown", LASER: "step:laser"},
    "doc_card": {"Halyard M1 parts breakdown": "breakdown"},
}


def in_document(document_id: str, caption: str, change_id: str) -> ProposedChange:
    return ProposedChange(
        change_id=change_id, operation="edit", chunk_id="chunk_12",
        document_id=document_id,
        old_html=figure(caption, "https://cdn.example/old.svg", chunked=True),
        new_html=figure(caption, "https://cdn.example/new.svg", chunked=True),
        explanation="updated the diagram")


def test_a_document_that_swapped_nothing_is_refused():
    """The live failure this check exists for. Asked to swap seven figures it
    does not contain and one it does, the card asked which were meant and
    changed nothing -- so the manual moved to the new drawings, the card kept
    the old one, and `assert_only_the_image_changed` saw eight clean swaps and
    was satisfied. That is the two documents disagreeing, reached through the
    path built to keep them together."""
    changes = [
        in_document("doc_manual",
                    "Halyard M1 parts breakdown. Numbers key to the table below.",
                    "c1"),
        in_document("doc_manual", LASER, "c2"),
    ]
    with pytest.raises(SuperDocsError, match="were not swapped"):
        session.assert_every_figure_swapped(changes, ASKED)


def test_a_document_that_swapped_only_some_of_its_figures_is_refused():
    changes = [in_document("doc_manual", LASER, "c1"),
               in_document("doc_card", "Halyard M1 parts breakdown", "c2")]
    with pytest.raises(SuperDocsError, match="parts breakdown. Numbers key"):
        session.assert_every_figure_swapped(changes, ASKED)


def test_every_figure_swapped_is_allowed():
    changes = [
        in_document("doc_manual",
                    "Halyard M1 parts breakdown. Numbers key to the table below.",
                    "c1"),
        in_document("doc_manual", LASER, "c2"),
        in_document("doc_card", "Halyard M1 parts breakdown", "c3"),
    ]
    session.assert_every_figure_swapped(changes, ASKED)


def test_the_two_checks_do_not_imply_each_other():
    """Neither check is redundant. An empty batch passes this one for every
    document nobody asked anything of, and a complete batch of rewritten prose
    passes the other -- so `sync` runs both."""
    session.assert_every_figure_swapped([], {})
    with pytest.raises(SuperDocsError, match="proposed no changes"):
        session.assert_only_the_image_changed([], IMAGES)


# ------------------------------------------------- the other refusal --

def test_an_edit_that_touched_only_one_document_is_refused(publication):
    """The drift this project exists to prevent, caught before it ships."""
    changes = [ProposedChange(
        change_id="c1", operation="edit", chunk_id="chunk_3",
        document_id=publication.manual_id, old_html="<p>1.2 N·m</p>",
        new_html="<p>1.6 N·m</p>", explanation="torque")]
    with pytest.raises(SuperDocsError, match="quick-start card"):
        session.assert_touched_both(publication, changes)


def test_an_edit_that_touched_both_is_allowed(publication):
    changes = [
        ProposedChange("c1", "edit", "chunk_3", publication.manual_id,
                       "<p>1.2 N·m</p>", "<p>1.6 N·m</p>", "torque"),
        ProposedChange("c2", "edit", "chunk_1", publication.card_id,
                       "<p>1.2 N·m</p>", "<p>1.6 N·m</p>", "torque"),
    ]
    session.assert_touched_both(publication, changes)


@pytest.fixture
def publication():
    return session.Publication(manual_id="doc_manual", card_id="doc_card")


def test_the_signature_the_service_appends_is_not_a_different_image():
    """Every image URL comes back with a 754-character signed query on it,
    because the service signs image links when it serves them. Comparing the
    strings refuses a correct swap; comparing nothing accepts a wrong one. The
    path is the file, the query is the signature."""
    signed = (IMAGES[LASER] + "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
              "&X-Goog-Credential=x&X-Goog-Date=20260811T000000Z"
              "&X-Goog-Expires=604800&X-Goog-Signature=" + "a" * 512)
    changes = [swap(figure(LASER, signed, chunked=True),
                    old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg",
                                    chunked=True))]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_a_different_file_with_a_valid_looking_signature_is_still_refused():
    """The check must not become "anything from that host". A signature on the
    wrong file is the wrong drawing, signed."""
    other = (IMAGES["Halyard M1 parts breakdown"]
             + "?X-Goog-Signature=" + "a" * 512)
    changes = [swap(figure(LASER, other, chunked=True),
                    old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg",
                                    chunked=True))]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)
