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

IMAGES = {
    "breakdown": "https://cdn.example/breakdown-v2.svg",
    "step:laser": "https://cdn.example/step_laser-v2.svg",
}


def figure(image_id: str, url: str, caption: str = "Step 4: Fit the laser module",
           extra: str = "") -> str:
    return (f'<figure data-block="step:laser:figure" data-diagram="{image_id}">'
            f'<img src="{url}" alt="{caption}"/>'
            f"<figcaption>{caption}</figcaption></figure>{extra}")


def swap(new_html: str, old_html: str | None = None,
         change_id: str = "c1") -> ProposedChange:
    return ProposedChange(
        change_id=change_id, operation="edit", chunk_id="chunk_12",
        document_id="doc_manual",
        old_html=old_html if old_html is not None else figure(
            "step:laser", "https://cdn.example/step_laser-v1.svg"),
        new_html=new_html, explanation="updated the diagram",
    )


def test_the_swap_that_is_only_a_swap_is_allowed():
    changes = [swap(figure("step:laser", IMAGES["step:laser"]))]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_a_reworded_caption_is_refused():
    """The likeliest failure, and the most reasonable-looking one: asked to
    change a URL, the turn tidies the caption while it is in there. A person
    reviewing forty of these approves it."""
    changes = [swap(figure("step:laser", IMAGES["step:laser"],
                           caption="Step 4: Fitting the laser module"))]
    with pytest.raises(SuperDocsError, match="altered more than the image URL"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_paragraph_added_next_to_the_figure_is_refused():
    changes = [swap(figure("step:laser", IMAGES["step:laser"],
                           extra="<p>See also the parts table.</p>"))]
    with pytest.raises(SuperDocsError, match="altered more than the image URL"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_plausible_url_that_was_never_uploaded_is_refused():
    """The single most likely thing for a model to produce here: a URL that
    looks exactly right. It renders as a broken image in a shipped manual, and
    it is the reason this check compares against what was uploaded rather than
    checking that the src merely changed."""
    invented = "https://cdn.example/step_laser-v3.svg"
    changes = [swap(figure("step:laser", invented))]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_the_right_url_on_the_wrong_figure_is_refused():
    """Both URLs are real and both were uploaded in this refresh. They are on
    the wrong figures, so every page still shows a diagram and two of them are
    the wrong drawing -- which is the failure a person is least likely to catch
    by reading a diff."""
    changes = [swap(figure("step:laser", IMAGES["breakdown"]))]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_figure_nobody_asked_about_is_refused():
    changes = [swap(
        new_html=figure("step:power", "https://cdn.example/step_power-v2.svg"),
        old_html=figure("step:power", "https://cdn.example/step_power-v1.svg"))]
    with pytest.raises(SuperDocsError, match="not part of this refresh"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_chunk_whose_figures_and_images_do_not_pair_up_is_refused():
    """Two figures and one image cannot be checked: whichever way they are
    paired, the pairing is a guess. A check that cannot be made is reported, not
    skipped."""
    two = (figure("breakdown", IMAGES["breakdown"])
           + '<figure data-diagram="step:laser"><figcaption>x</figcaption></figure>')
    changes = [swap(new_html=two, old_html=two.replace("-v2", "-v1"))]
    with pytest.raises(SuperDocsError, match="pairing"):
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
        swap(figure("breakdown", IMAGES["breakdown"]), change_id="ok"),
        swap(figure("step:laser", IMAGES["step:laser"], caption="Reworded"),
             change_id="bad"),
    ]
    with pytest.raises(SuperDocsError, match="whole batch was refused"):
        session.assert_only_the_image_changed(changes, IMAGES)


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
