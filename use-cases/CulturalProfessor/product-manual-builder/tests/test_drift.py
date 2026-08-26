"""The pair coming apart on one passage, and being put back together.

`assert_touched_both_or_absent` asks whether each document proposed
*something*. That is the question that catches a card nobody edited, and it is
not the question this file is about.

Asked to raise a torque figure, the manual's turn found three passages -- the
rails step, the gantry step, and the troubleshooting table's own re-torque line
-- and the card's turn found two of its three. Both documents proposed
something, the batch passed every guard, and the pair came apart on the one
passage the card missed. `verify` said so afterwards, correctly and far too
late: the documents were already published that way.

So the pair is compared passage by passage as soon as a batch lands, and the
document that was left behind is asked to say what the other one says. These
tests are that comparison and that repair: which document lagged, what it is
told, and every way the repair itself is refused.

No network. A served document is a string and a proposed change is a
dataclass.
"""

from __future__ import annotations

import json

import pytest

from manualbuilder import cli, session
from manualbuilder import verify as vf
from manualbuilder.superdocs import ProposedChange, SuperDocsError

from .conftest import PROJECT_ROOT
from .test_verify import both, urls

FIX = "fix out_of_square"


def _fix(spec):
    return next(f for f in spec.quick_start_troubleshooting() if f.id == "out_of_square")


def _pair(spec, manual_torque: str = "1.2", card_torque: str = "1.2") -> dict[str, str]:
    """The published pair, with the shared troubleshooting line worded per role."""
    fix = _fix(spec)
    pair = both(spec, urls(spec))
    return {
        vf.MANUAL: pair[vf.MANUAL].replace(fix.fix, fix.fix.replace("1.2", manual_torque)),
        vf.CARD: pair[vf.CARD].replace(fix.fix, fix.fix.replace("1.2", card_torque)),
    }


# ------------------------------------------------------- finding the drift --


def test_a_pair_that_still_agrees_has_drifted_on_nothing(spec):
    assert session.drifted(_pair(spec), spec) == []
    assert session.drifted(_pair(spec, "1.6", "1.6"), spec) == [], "edited, and still agreeing"


def test_the_passage_one_document_missed_names_the_document_that_missed_it(spec):
    """The live failure. The manual's turn found the troubleshooting line and
    the card's turn did not, so the card is the straggler -- it still reads the
    way the spec words it, and the manual does not."""
    drifts = session.drifted(_pair(spec, manual_torque="1.6"), spec)

    assert len(drifts) == 1
    drift = drifts[0]
    assert drift.label == FIX
    assert drift.lagging == vf.CARD and drift.repairable
    assert "1.2 N·m" in drift.behind, "what the card says now"
    assert "1.6 N·m" in drift.ahead, "what the manual says now, and what the card must say"


def test_either_document_can_be_the_one_that_lagged(spec):
    """Nothing here privileges the manual. The card is edited and the manual is
    not, and the manual is named as the straggler."""
    drifts = session.drifted(_pair(spec, card_torque="1.6"), spec)

    assert [d.lagging for d in drifts] == [vf.MANUAL]
    assert "1.6 N·m" in drifts[0].ahead


def test_both_documents_moving_differently_is_not_something_to_repair(spec):
    """A manual reading 1.6 beside a card reading 1.8 is a real disagreement and
    an unanswerable one: neither wording is the one that was there before, so
    picking either would be inventing the answer rather than finding it."""
    drifts = session.drifted(_pair(spec, "1.6", "1.8"), spec)

    assert len(drifts) == 1 and not drifts[0].repairable
    with pytest.raises(SuperDocsError, match="question for a person"):
        session.realign(_Refuses(), _publication(), drifts)


def test_what_drifted_and_what_verify_fails_are_the_same_passages(spec):
    """The two run off one list -- `shared_items` -- because a passage that is
    repaired and never checked, or checked and never repaired, is the same bug
    in two different disguises."""
    pair = _pair(spec, manual_torque="1.6")

    failed = {finding.check for finding in vf.failed(vf.pair_findings(pair, spec))}
    assert failed == {drift.label for drift in session.drifted(pair, spec)} == {FIX}


# ------------------------------------------------------------ the repair --


def _publication() -> session.Publication:
    return session.Publication(
        manual_id="doc_m",
        card_id="doc_c",
        sessions={"doc_m": "s_manual", "doc_c": "s_card"},
        durable={"doc_m": "uuid-m", "doc_c": "uuid-c"},
    )


class _Refuses:
    """A client every call on which is a test failure."""

    def __getattr__(self, name):  # pragma: no cover
        raise AssertionError(f"nothing should have called {name}")


class _Turn:
    """One turn, whose proposed changes the test supplies."""

    def __init__(self, changes: list[ProposedChange]):
        self.changes, self.asked = changes, {}

    def active_jobs(self, session_id):
        return []

    def chat_async(self, message, session_id, document_id=None):
        self.asked[document_id] = message
        return f"job_{document_id}"

    def wait_for_job(self, job_id):
        return {"status": "awaiting_approval", "metadata": {"pending_changes": []}}

    def pending_changes(self, job):
        return self.changes


def _row(fix, torque: str) -> str:
    """The troubleshooting table as a chunk: three rows, one of them the fix."""
    return (
        '<table data-chunk-id="chunk_table"><tbody>'
        "<tr><td>No fire</td><td>Check the interlock.</td></tr>"
        f"<tr><td>Out of square</td><td>{fix.fix.replace('1.2', torque)}</td></tr>"
        "<tr><td>No power</td><td>Check the fuse.</td></tr>"
        "</tbody></table>"
    )


def _para(fix, torque: str) -> str:
    """The fix as its own paragraph chunk, which is what the card holds."""
    return f'<p data-chunk-id="chunk_fix">{fix.fix.replace("1.2", torque)}</p>'


def _proposed(old: str, new: str, change_id: str = "r1") -> ProposedChange:
    return ProposedChange(
        change_id=change_id,
        operation="edit",
        chunk_id="chunk_table",
        document_id="doc_c",
        old_html=old,
        new_html=new,
        explanation="brought the torque figure in line",
    )


def test_the_document_that_lagged_is_the_only_one_asked_and_is_handed_the_words(spec):
    """The wording it has to produce is in the instruction verbatim rather than
    described. A model is being used to find a passage, not to decide what it
    should say -- and the document that was already right is not asked
    anything, because a turn costs an operation and it has nothing to do."""
    fix = _fix(spec)
    drifts = session.drifted(_pair(spec, manual_torque="1.6"), spec)
    client = _Turn([_proposed(_row(fix, "1.2"), _row(fix, "1.6"))])

    changes = session.realign(client, _publication(), drifts)

    assert list(client.asked) == ["doc_c"], "only the straggler is sent a turn"
    assert drifts[0].ahead in client.asked["doc_c"], "the exact new wording, not a description"
    assert drifts[0].behind in client.asked["doc_c"], "and the passage to find it by"
    assert [c.change_id for c in changes] == ["r1"]


def test_a_repair_that_moved_a_second_row_is_refused(spec):
    """The chunk is a whole table and only one row of it was in the
    instruction. Every other row has to come back character for character."""
    fix = _fix(spec)
    drifts = session.drifted(_pair(spec, manual_torque="1.6"), spec)
    meddled = _row(fix, "1.6").replace("Check the fuse.", "Check the fuse and the switch.")
    client = _Turn([_proposed(_row(fix, "1.2"), meddled)])

    with pytest.raises(SuperDocsError, match="did not make chunk"):
        session.realign(client, _publication(), drifts)


def test_a_repair_that_proposed_nothing_is_refused(spec):
    """`verify` found the passage in this document, and the wording to give it
    was in the instruction. A turn that comes back empty has not agreed that
    there is nothing to do -- it has left the pair disagreeing."""
    drifts = session.drifted(_pair(spec, manual_torque="1.6"), spec)

    with pytest.raises(SuperDocsError, match="still disagree"):
        session.realign(_Turn([]), _publication(), drifts)


def test_a_repair_that_fixed_a_different_passage_is_refused(spec):
    """Right document, wrong passage: the rails step edited instead of the
    troubleshooting line. It reads like a fix and it leaves the disagreement
    exactly where it was."""
    rails = next(step for step in spec.quick_start() if step.id == "rails")
    drifts = session.drifted(_pair(spec, manual_torque="1.6"), spec)
    client = _Turn(
        [
            _proposed(
                f'<p data-chunk-id="chunk_rails">{rails.body}</p>',
                f'<p data-chunk-id="chunk_rails">{rails.body.replace("1.2", "1.6")}</p>',
            )
        ]
    )

    with pytest.raises(SuperDocsError, match="did not make chunk"):
        session.realign(client, _publication(), drifts)


# ------------------------------------------------- the whole thing, wired --


def test_approve_puts_the_pair_back_together_and_says_what_it_spent(
    monkeypatch, tmp_path, capsys, spec
):
    """The demo's own failure, end to end: a batch is approved, the read-back
    shows the card still wording the troubleshooting line the old way, and
    `approve` asks the card -- one operation -- to say what the manual says
    rather than leaving somebody to find out from `verify`."""
    fix = _fix(spec)
    state = {"card_torque": "1.2"}

    class FakeClient:
        def __init__(self):
            self.turn = _Turn([_proposed(_para(fix, "1.2"), _para(fix, "1.6"))])
            self.approved: list[dict] = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            pair = _pair(spec, manual_torque="1.6", card_torque=state["card_torque"])
            return pair[vf.MANUAL if durable_id == "uuid-m" else vf.CARD]

        def approve(self, session_id, job_id, decisions, approved_by_default=True):
            self.approved.append(decisions)
            # The second approval is the repair; applying it is what makes the
            # card read the way the manual does.
            if "r1" in decisions:
                state["card_torque"] = "1.6"
            return {"status": "ok"}

        def __getattr__(self, name):
            return getattr(self.turn, name)

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(
        json.dumps(
            {
                "manual_id": "doc_m",
                "card_id": "doc_c",
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "durable": {"doc_m": "uuid-m", "doc_c": "uuid-c"},
                "language": "",
                "images": {},
            }
        )
    )
    (out / "proposal.json").write_text(
        json.dumps(
            {
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "jobs": {"doc_m": "job_m", "doc_c": "job_c"},
                "changes": [
                    {
                        "change_id": "c1",
                        "operation": "edit",
                        "chunk_id": "chunk_fix",
                        "document_id": "doc_m",
                        "old_html": _para(fix, "1.2"),
                        "new_html": _para(fix, "1.6"),
                        "explanation": "raised the torque",
                    }
                ],
            }
        )
    )

    client = FakeClient()
    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: client)
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.setattr(cli.session, "SETTLE_TIMEOUT", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["approve"])
    printed = capsys.readouterr().out

    assert code == 0
    assert "the pair came apart on 1 passage(s)" in printed
    assert FIX in printed
    assert "-1.2 +1.6" in printed, "the words that differ, not two passages truncated alike"
    assert "1 operation" in printed, "an operation spent inside a free command has to be announced"
    assert "agree again" in printed
    assert list(client.turn.asked) == ["doc_c"]
    assert client.approved[-1] == {"r1": True}
    assert not session.drifted(session.read_pair(client, _publication()), spec)


def test_no_repair_reports_the_drift_and_spends_nothing(monkeypatch, tmp_path, capsys, spec):
    """The same run with `--no-repair`: the disagreement is named, no turn is
    sent, and the command comes back non-zero because the pair is wrong."""
    fix = _fix(spec)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            pair = _pair(spec, manual_torque="1.6")
            return pair[vf.MANUAL if durable_id == "uuid-m" else vf.CARD]

        def approve(self, session_id, job_id, decisions, approved_by_default=True):
            return {"status": "ok"}

        def chat_async(self, *a, **kw):  # pragma: no cover
            raise AssertionError("--no-repair must not send a turn")

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(
        json.dumps(
            {
                "manual_id": "doc_m",
                "card_id": "doc_c",
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "durable": {"doc_m": "uuid-m", "doc_c": "uuid-c"},
                "language": "",
                "images": {},
            }
        )
    )
    (out / "proposal.json").write_text(
        json.dumps(
            {
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "jobs": {"doc_m": "job_m"},
                "changes": [
                    {
                        "change_id": "c1",
                        "operation": "edit",
                        "chunk_id": "chunk_fix",
                        "document_id": "doc_m",
                        "old_html": _para(fix, "1.2"),
                        "new_html": _para(fix, "1.6"),
                        "explanation": "raised the torque",
                    }
                ],
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.setattr(cli.session, "SETTLE_TIMEOUT", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["approve", "--no-repair"])
    printed = capsys.readouterr().out

    assert code == 1
    assert FIX in printed and "--no-repair" in printed
    assert "the manual and the card disagree" in printed


# ------------------------------------- a refresh that moved a word anyway --


def test_approve_refuses_to_call_a_refresh_clean_when_the_wording_moved(
    monkeypatch, tmp_path, capsys, spec
):
    """`sync` proves every proposed change was an image URL, which is a claim
    about the batch. This is the claim about the documents, checked after the
    write: a diagram refresh must leave the text exactly as it read before it.

    It is here because of one observation nothing else explains -- a passage
    that read 1.6 N·m in both documents read 1.2 in both a few minutes later,
    with a diagram refresh in between, and every check passed either way. This
    does not prevent that. It makes it loud."""
    fix = _fix(spec)
    before = _pair(spec, manual_torque="1.6", card_torque="1.6")
    after = _pair(spec, manual_torque="1.2", card_torque="1.2")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            return after[vf.MANUAL if durable_id == "uuid-m" else vf.CARD]

        def approve(self, session_id, job_id, decisions, approved_by_default=True):
            return {"status": "ok"}

        def chat_async(self, *a, **kw):  # pragma: no cover
            raise AssertionError("a wording check must not send a turn")

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(
        json.dumps(
            {
                "manual_id": "doc_m",
                "card_id": "doc_c",
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "durable": {"doc_m": "uuid-m", "doc_c": "uuid-c"},
                "language": "",
                "images": {},
            }
        )
    )
    (out / "proposal.json").write_text(
        json.dumps(
            {
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "jobs": {"doc_m": "job_m"},
                "unchanged_text": {
                    "doc_m": vf.text_of(before[vf.MANUAL]),
                    "doc_c": vf.text_of(before[vf.CARD]),
                },
                "changes": [
                    {
                        "change_id": "s1",
                        "operation": "edit",
                        "chunk_id": "chunk_figure",
                        "document_id": "doc_m",
                        "old_html": '<p data-chunk-id="chunk_figure"><img alt="a" src="old.svg"/></p>',
                        "new_html": '<p data-chunk-id="chunk_figure"><img alt="a" src="new.svg"/></p>',
                        "explanation": "swapped the drawing",
                    }
                ],
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.setattr(cli.session, "SETTLE_TIMEOUT", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["approve"])
    printed = capsys.readouterr().out

    assert code == 1
    assert "the wording moved" in printed
    assert "-1.6 +1.2" in printed, "the words that moved, not the fact that some did"
    assert fix.fix  # the passage this is about is a real one in the spec


def test_a_refresh_that_really_changed_nothing_says_nothing_about_wording(
    monkeypatch, tmp_path, capsys, spec
):
    """The check has to be silent when it passes, or every clean refresh grows
    a paragraph about the one that did not."""
    pair = _pair(spec, manual_torque="1.6", card_torque="1.6")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            return pair[vf.MANUAL if durable_id == "uuid-m" else vf.CARD]

        def approve(self, session_id, job_id, decisions, approved_by_default=True):
            return {"status": "ok"}

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(
        json.dumps(
            {
                "manual_id": "doc_m",
                "card_id": "doc_c",
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "durable": {"doc_m": "uuid-m", "doc_c": "uuid-c"},
                "language": "",
                "images": {},
            }
        )
    )
    (out / "proposal.json").write_text(
        json.dumps(
            {
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "jobs": {"doc_m": "job_m"},
                "unchanged_text": {
                    "doc_m": vf.text_of(pair[vf.MANUAL]),
                    "doc_c": vf.text_of(pair[vf.CARD]),
                },
                "changes": [
                    {
                        "change_id": "s1",
                        "operation": "edit",
                        "chunk_id": "chunk_figure",
                        "document_id": "doc_m",
                        "old_html": '<p data-chunk-id="chunk_figure"><img alt="a" src="old.svg"/></p>',
                        "new_html": '<p data-chunk-id="chunk_figure"><img alt="a" src="new.svg"/></p>',
                        "explanation": "swapped the drawing",
                    }
                ],
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.setattr(cli.session, "SETTLE_TIMEOUT", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["approve"])
    printed = capsys.readouterr().out

    assert code == 0
    assert "the wording moved" not in printed
