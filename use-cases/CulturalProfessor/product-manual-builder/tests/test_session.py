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
        return (
            f'<figure data-chunk-id="f248c6f2"><img alt="{caption}" '
            f'src="{url}"/><figcaption>{caption}</figcaption></figure>{extra}'
        )
    return (
        f'<figure data-block="step:laser:figure" data-diagram="step:laser">'
        f'<img src="{url}" alt="{caption}"/>'
        f"<figcaption>{caption}</figcaption></figure>{extra}"
    )


def swap(new_html: str, old_html: str | None = None, change_id: str = "c1") -> ProposedChange:
    return ProposedChange(
        change_id=change_id,
        operation="edit",
        chunk_id="chunk_12",
        document_id="doc_manual",
        old_html=(
            old_html
            if old_html is not None
            else figure(LASER, "https://cdn.example/step_laser-v1.svg")
        ),
        new_html=new_html,
        explanation="updated the diagram",
    )


def test_the_swap_that_is_only_a_swap_is_allowed():
    changes = [swap(figure(LASER, IMAGES[LASER]))]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_the_shape_the_service_actually_returns_is_allowed():
    """The same swap, in the markup a real chunk comes back as: attributes
    stripped, a chunk id added, alt before src. The first live run refused this
    because the check was reading the markup we sent rather than the markup that
    came back."""
    changes = [
        swap(
            new_html=figure(LASER, IMAGES[LASER], chunked=True),
            old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg", chunked=True),
        )
    ]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_a_reworded_caption_is_refused():
    """The likeliest failure, and the most reasonable-looking one: asked to
    change a URL, the turn tidies the caption while it is in there. A person
    reviewing forty of these approves it."""
    changes = [swap(figure("Step 4: Fitting the laser module", IMAGES[LASER]))]
    with pytest.raises(SuperDocsError, match="altered more than the image URL"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_a_paragraph_added_next_to_the_figure_is_refused():
    changes = [swap(figure(LASER, IMAGES[LASER], extra="<p>See also the parts table.</p>"))]
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
    changes = [
        swap(
            new_html=figure("Step 6: Power up and home", "https://cdn.example/step_power-v2.svg"),
            old_html=figure("Step 6: Power up and home", "https://cdn.example/step_power-v1.svg"),
        )
    ]
    with pytest.raises(SuperDocsError, match="not part of this refresh"):
        session.assert_only_the_image_changed(changes, IMAGES)


def test_an_image_with_no_caption_to_identify_it_is_refused():
    """A figure whose alt text was dropped cannot be checked: there is nothing
    left saying which drawing it is meant to be. A check that cannot be made is
    reported, not skipped."""
    anonymous = '<figure><img src="https://cdn.example/step_laser-v2.svg"/></figure>'
    changes = [swap(new_html=anonymous, old_html=anonymous.replace("-v2", "-v1"))]
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
        swap(
            figure("Halyard M1 parts breakdown", IMAGES["Halyard M1 parts breakdown"]),
            change_id="ok",
        ),
        swap(figure("Reworded", IMAGES[LASER]), change_id="bad"),
    ]
    with pytest.raises(SuperDocsError, match="whole batch was refused"):
        session.assert_only_the_image_changed(changes, IMAGES)


# ------------------------------------- the figure that was left behind --

#: What each document was asked to swap: the manual holds both figures, the card
#: holds only the breakdown, and it captions it differently.
ASKED = {
    "doc_manual": {
        "Halyard M1 parts breakdown. Numbers key to the table below.": "breakdown",
        LASER: "step:laser",
    },
    "doc_card": {"Halyard M1 parts breakdown": "breakdown"},
}


def in_document(document_id: str, caption: str, change_id: str) -> ProposedChange:
    return ProposedChange(
        change_id=change_id,
        operation="edit",
        chunk_id="chunk_12",
        document_id=document_id,
        old_html=figure(caption, "https://cdn.example/old.svg", chunked=True),
        new_html=figure(caption, "https://cdn.example/new.svg", chunked=True),
        explanation="updated the diagram",
    )


def test_a_document_that_swapped_nothing_is_refused():
    """The live failure this check exists for. Asked to swap seven figures it
    does not contain and one it does, the card asked which were meant and
    changed nothing -- so the manual moved to the new drawings, the card kept
    the old one, and `assert_only_the_image_changed` saw eight clean swaps and
    was satisfied. That is the two documents disagreeing, reached through the
    path built to keep them together."""
    changes = [
        in_document(
            "doc_manual", "Halyard M1 parts breakdown. Numbers key to the table below.", "c1"
        ),
        in_document("doc_manual", LASER, "c2"),
    ]
    with pytest.raises(SuperDocsError, match="were not swapped"):
        session.assert_every_figure_swapped(changes, ASKED)


def test_a_document_that_swapped_only_some_of_its_figures_is_refused():
    changes = [
        in_document("doc_manual", LASER, "c1"),
        in_document("doc_card", "Halyard M1 parts breakdown", "c2"),
    ]
    with pytest.raises(SuperDocsError, match=r"parts breakdown\. Numbers key"):
        session.assert_every_figure_swapped(changes, ASKED)


def test_every_figure_swapped_is_allowed():
    changes = [
        in_document(
            "doc_manual", "Halyard M1 parts breakdown. Numbers key to the table below.", "c1"
        ),
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
    changes = [
        ProposedChange(
            change_id="c1",
            operation="edit",
            chunk_id="chunk_3",
            document_id=publication.manual_id,
            old_html="<p>1.2 N·m</p>",
            new_html="<p>1.6 N·m</p>",
            explanation="torque",
        )
    ]
    with pytest.raises(SuperDocsError, match="quick-start card"):
        session.assert_touched_both(publication, changes)


def test_a_document_with_a_turn_already_in_flight_refuses_the_next_edit(publication):
    """The guard at the top of `edit_each`. A batch nobody decided on holds its
    session open, and the service answers the next turn with 409 `session_busy`
    -- correct, and four frames deep in a stack trace. Checked here instead, so
    the failure names what is in the way and how to clear it, and so a second
    `chat_async` is never sent into a session that is already holding one."""
    publication.sessions = {"doc_manual": "s_manual", "doc_card": "s_card"}

    class Fake:
        def active_jobs(self, session_id):
            return [{"job_id": "job_old", "status": "awaiting_approval"}]

        def chat_async(self, *a, **k):  # pragma: no cover
            raise AssertionError("a turn was sent while one was still parked")

    with pytest.raises(SuperDocsError, match=r"already has 1 turn.*waiting to be approved"):
        session.edit_both(Fake(), publication, "raise the rail torque to 1.6 N·m")


def test_an_edit_that_touched_both_is_allowed(publication):
    changes = [
        ProposedChange(
            "c1",
            "edit",
            "chunk_3",
            publication.manual_id,
            "<p>1.2 N·m</p>",
            "<p>1.6 N·m</p>",
            "torque",
        ),
        ProposedChange(
            "c2",
            "edit",
            "chunk_1",
            publication.card_id,
            "<p>1.2 N·m</p>",
            "<p>1.6 N·m</p>",
            "torque",
        ),
    ]
    session.assert_touched_both(publication, changes)


def _spec_table_change(document_id: str) -> ProposedChange:
    """The change that started this: a manual-only Specifications table edit,
    with a whole `<table>` chunk as `old_html` -- the actual shape `edit`
    prints, not a simplified stand-in for it."""
    return ProposedChange(
        change_id="c1",
        operation="edit",
        chunk_id="chunk_specs",
        document_id=document_id,
        old_html=(
            "<table><thead><tr><th>Specification</th><th>Value</th></tr></thead>"
            "<tbody><tr><td>Work area</td><td>400 × 500 mm</td></tr>"
            "<tr><td>Laser source</td><td>450 nm diode laser</td></tr></tbody></table>"
        ),
        new_html=(
            "<table><thead><tr><th>Specification</th><th>Value</th></tr></thead>"
            "<tbody><tr><td>Work area</td><td>400 × 600 mm</td></tr>"
            "<tr><td>Laser source</td><td>460 nm diode laser</td></tr></tbody></table>"
        ),
        explanation="updated the specifications",
    )


def test_excusably_empty_is_true_when_nothing_resembles_the_change():
    """The card never renders a Specifications section at all -- none of its
    real content is anywhere close to a table of work-area and wavelength
    values, so an empty reply from it is not the pair coming apart."""
    change = _spec_table_change("doc_manual")
    card_html = (
        "<h2>Setup</h2><p>Unpack the crate and check the parts against the "
        "table below.</p><p>Fit the rails to the base frame.</p>"
    )
    assert session.excusably_empty([change], card_html) is True


def test_excusably_empty_is_false_when_the_old_wording_is_still_there():
    """The ordinary case `assert_touched_both` exists for: the card holds the
    torque figure too, in its own words, and an empty reply from it means the
    turn missed a document it should have touched -- not that the fact was
    never there."""
    change = ProposedChange(
        "c1",
        "edit",
        "chunk_3",
        "doc_manual",
        "<p>Torque the rail screws to 1.2 N·m.</p>",
        "<p>Torque the rail screws to 1.6 N·m.</p>",
        "torque",
    )
    card_html = "<h2>Rails</h2><p>Torque the rail screws to 1.2 N·m.</p>"
    assert session.excusably_empty([change], card_html) is False


def test_assert_touched_both_or_absent_excuses_a_manual_only_fact():
    """The wiring, not just the pure check: a Specifications edit that only
    touches the manual is let through, and the card is named as excused
    rather than passed over silently."""
    publication = session.Publication(
        manual_id="doc_manual",
        card_id="doc_card",
        durable={"doc_manual": "uuid-m", "doc_card": "uuid-c"},
    )
    changes = [_spec_table_change("doc_manual")]

    class Fake:
        def document_html(self, durable_id):
            assert durable_id == "uuid-c", "only the empty document needs reading"
            return "<h2>Setup</h2><p>Fit the rails to the base frame.</p>"

    excused = session.assert_touched_both_or_absent(Fake(), publication, changes)
    assert excused == ["doc_card"]


def test_assert_touched_both_or_absent_still_refuses_real_drift():
    """The case this whole guard exists for is untouched: a fact the card
    genuinely holds, proposed only in the manual, is still refused -- being
    able to excuse an absent document must not make a present one optional."""
    publication = session.Publication(
        manual_id="doc_manual",
        card_id="doc_card",
        durable={"doc_manual": "uuid-m", "doc_card": "uuid-c"},
    )
    changes = [
        ProposedChange(
            "c1",
            "edit",
            "chunk_3",
            "doc_manual",
            "<p>Torque the rail screws to 1.2 N·m.</p>",
            "<p>Torque the rail screws to 1.6 N·m.</p>",
            "torque",
        )
    ]

    class Fake:
        def document_html(self, durable_id):
            return "<h2>Rails</h2><p>Torque the rail screws to 1.2 N·m.</p>"

    with pytest.raises(SuperDocsError, match="quick-start card"):
        session.assert_touched_both_or_absent(Fake(), publication, changes)


@pytest.fixture
def publication():
    return session.Publication(manual_id="doc_manual", card_id="doc_card")


def test_ask_opens_a_fresh_session_and_leaves_edits_session_alone():
    """`ask` and `edit` must never share a session. A live run found why: a
    question about the rail step's torque -- which the step's own sentence
    states plainly -- came back "the document does not specify" one, and the
    very next `edit` sent into that same session took its own wrong answer at
    its word, adding a second, invented torque figure instead of finding the
    real one. `ask` opens a session of its own per call and never records it,
    so whatever `edit` remembers is exactly as it was before the question."""
    sent: dict = {}
    publication = session.Publication(
        manual_id="doc_manual",
        card_id="doc_card",
        sessions={"doc_manual": "s_manual", "doc_card": "s_card"},
        durable={"doc_manual": "dur_manual", "doc_card": "dur_card"},
    )

    class Fake:
        def init_session(self, document_ids=None):
            return "s_manual_fresh"

        def documents(self, session_id):
            return [{"document_id": "doc_manual"}]

        def chat(self, message, session_id, document_id=None, thinking_depth=None, **kw):
            sent["message"] = message
            sent["session_id"] = session_id
            sent["document_id"] = document_id
            sent["thinking_depth"] = thinking_depth
            return {"response": "The laser runs at 5 W.", "session_id": session_id}

    reply = session.ask(Fake(), publication, publication.manual_id, "what is the max laser power?")

    assert sent["session_id"] == "s_manual_fresh", "must not reuse the session edit uses"
    assert sent["document_id"] == "doc_manual"
    assert sent["thinking_depth"] == "fast"
    assert reply["response"] == "The laser runs at 5 W."
    assert publication.sessions == {
        "doc_manual": "s_manual",
        "doc_card": "s_card",
    }, "the fresh session must not be written back -- edit's session is untouched"


def test_ask_is_unaffected_by_a_parked_batch_on_edits_session():
    """The busy-session guard `edit_each` uses does not apply here, and
    should not: a parked batch lives on the session `edit` uses, `ask` never
    touches that session at all, so a question can be answered regardless of
    what review is sitting unresolved on it."""
    publication = session.Publication(
        manual_id="doc_manual",
        card_id="doc_card",
        sessions={"doc_manual": "s_manual", "doc_card": "s_card"},
        durable={"doc_manual": "dur_manual", "doc_card": "dur_card"},
    )

    class Fake:
        def init_session(self, document_ids=None):
            return "s_manual_fresh"

        def documents(self, session_id):
            return [{"document_id": "doc_manual"}]

        def active_jobs(self, session_id):  # pragma: no cover
            raise AssertionError("ask must not inspect edit's session at all")

        def chat(self, message, session_id, document_id=None, thinking_depth=None, **kw):
            return {"response": "answered anyway", "session_id": session_id}

    reply = session.ask(Fake(), publication, publication.manual_id, "any question")
    assert reply["response"] == "answered anyway"


def test_the_signature_the_service_appends_is_not_a_different_image():
    """Every image URL comes back with a 754-character signed query on it,
    because the service signs image links when it serves them. Comparing the
    strings refuses a correct swap; comparing nothing accepts a wrong one. The
    path is the file, the query is the signature."""
    signed = (
        IMAGES[LASER] + "?X-Goog-Algorithm=GOOG4-RSA-SHA256"
        "&X-Goog-Credential=x&X-Goog-Date=20260811T000000Z"
        "&X-Goog-Expires=604800&X-Goog-Signature=" + "a" * 512
    )
    changes = [
        swap(
            figure(LASER, signed, chunked=True),
            old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg", chunked=True),
        )
    ]
    session.assert_only_the_image_changed(changes, IMAGES)


def test_a_different_file_with_a_valid_looking_signature_is_still_refused():
    """The check must not become "anything from that host". A signature on the
    wrong file is the wrong drawing, signed."""
    other = IMAGES["Halyard M1 parts breakdown"] + "?X-Goog-Signature=" + "a" * 512
    changes = [
        swap(
            figure(LASER, other, chunked=True),
            old_html=figure(LASER, "https://cdn.example/step_laser-v1.svg", chunked=True),
        )
    ]
    with pytest.raises(SuperDocsError, match="not the URL uploaded for it"):
        session.assert_only_the_image_changed(changes, IMAGES)


# ------------------------------- the session that stopped holding it --


class _Sessions:
    """A service where a session serves whatever it is focused on.

    Which is what the real one does, and why `ensure_sessions` exists: export
    is keyed by session, so a session that has been re-focused elsewhere hands
    back a different document under the same call.
    """

    def __init__(self, holding: dict[str, list[str]]):
        self.holding = holding
        self.opened: list[list[str]] = []

    def documents(self, session_id):
        return [{"document_id": d} for d in self.holding.get(session_id, [])]

    def init_session(self, document_ids=None):
        self.opened.append(list(document_ids or []))
        name = f"session_fresh_{len(self.opened)}"
        # A fresh session opened on a durable id holds exactly that document.
        durable_to_doc = {"dur_manual": "doc_manual", "dur_card": "doc_card"}
        self.holding[name] = [durable_to_doc[d] for d in (document_ids or [])]
        return name


def _pair() -> session.Publication:
    return session.Publication(
        manual_id="doc_manual",
        card_id="doc_card",
        sessions={"doc_manual": "s_manual", "doc_card": "s_card"},
        durable={"doc_manual": "dur_manual", "doc_card": "dur_card"},
    )


def test_a_session_still_holding_its_document_is_left_alone():
    publication = _pair()
    client = _Sessions({"s_manual": ["doc_manual"], "s_card": ["doc_card"]})

    assert publication.ensure_sessions(client) == []
    assert publication.sessions == {"doc_manual": "s_manual", "doc_card": "s_card"}
    assert client.opened == [], "nothing needed re-opening, so nothing was opened"


def test_a_session_serving_a_different_document_is_re_opened():
    """The live failure. Opening the pair in the web interface and focusing the
    other tab left the card's recorded session serving the manual -- same call,
    same session id, different document, no error. `verify` then reported the
    card as having eight figures and disagreeing with the manual, which was
    true of the document it was handed and nothing to do with the card."""
    publication = _pair()
    client = _Sessions({"s_manual": ["doc_manual"], "s_card": ["doc_manual"]})

    assert publication.ensure_sessions(client) == ["doc_card"]
    assert publication.sessions["doc_manual"] == "s_manual", "untouched"
    assert publication.sessions["doc_card"] != "s_card"
    assert client.opened == [["dur_card"]], "re-opened by durable id, not by doc id"
    # And the new session really does hold the card.
    held = client.documents(publication.sessions["doc_card"])
    assert [d["document_id"] for d in held] == ["doc_card"]


def test_a_document_with_no_durable_id_recorded_says_so():
    """Without a durable id there is no way to re-open it, and guessing with
    the session-scoped id gets "None of the requested documents were found"."""
    publication = _pair()
    publication.durable.pop("doc_card")
    client = _Sessions({"s_manual": ["doc_manual"], "s_card": ["doc_manual"]})

    with pytest.raises(SuperDocsError, match="no durable id recorded"):
        publication.ensure_sessions(client)
