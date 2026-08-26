"""The two commands a stranger runs first, run.

Every other test file checks a piece. This one checks that the pieces are wired
to the command line, because a `check` that passes while never reaching the
pagination assertion is worse than no check at all: it prints `ok` in a colour
somebody trusts.

Nothing here touches the network or needs a key, which is the same promise
`check` and `build` make.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from manualbuilder import cli

from .conftest import PROJECT_ROOT


def _run(monkeypatch, argv: list[str], capsys) -> tuple[int, str]:
    monkeypatch.chdir(PROJECT_ROOT)
    code = cli.main(argv)
    return code, capsys.readouterr().out


def test_check_passes_on_what_ships(monkeypatch, capsys):
    code, out = _run(monkeypatch, ["check"], capsys)
    assert code == 0
    assert out.strip().endswith("ok")
    assert "FAIL" not in out
    # The numbers are the point of the command; a silent pass is not a report.
    assert "pages" in out and "headroom" in out
    for language in ("de", "fr"):
        assert f"locale {language}" in out


def test_check_fails_and_says_where_when_a_locale_runs_long(monkeypatch, tmp_path, capsys):
    """The wiring that matters. A locale is lengthened until it repaginates, and
    `check` has to come back non-zero with the block named -- not with a
    traceback, and not with `ok`."""
    locales = tmp_path / "locales"
    locales.mkdir()
    raw = yaml.safe_load((PROJECT_ROOT / "locales" / "de.yaml").read_text())
    for warning in raw["warnings"].values():
        warning["body"] = " ".join([warning["body"]] * 3)
    (locales / "de.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))

    monkeypatch.setattr(cli, "LOCALES", locales)
    code, out = _run(monkeypatch, ["check"], capsys)

    assert code == 1
    assert "FAIL" in out
    assert "would repaginate" in out
    assert "safety:warning:" in out, "the report must name the block that moved"


def test_build_writes_a_document_per_language_and_its_diagrams(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    code, _out = _run(monkeypatch, ["build"], capsys)
    assert code == 0

    written = {path.name for path in (tmp_path / "out").iterdir()}
    for name in (
        "manual.html",
        "quickstart.html",
        "manual.de.html",
        "manual.fr.html",
        "manual.preview.html",
    ):
        assert name in written

    # The drawings are per language too, not the English ones reused.
    assert {"breakdown.svg", "breakdown.de.svg", "breakdown.fr.svg"} <= written
    english = (tmp_path / "out" / "breakdown.svg").read_text()
    german = (tmp_path / "out" / "breakdown.de.svg").read_text()
    assert english != german
    assert "Grundrahmen" in german


def test_the_preview_marks_every_page_the_layout_found(monkeypatch, tmp_path, capsys):
    """The preview is what makes the pagination claim something you can look at.
    If it drew fewer rules than there are pages it would be a picture of a
    different document."""
    from manualbuilder import paginate as pg
    from manualbuilder import projections as pj
    from manualbuilder.spec import load_spec

    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    _run(monkeypatch, ["build"], capsys)

    spec = load_spec(PROJECT_ROOT / "spec" / "halyard_m1.yaml")
    pages = pg.paginate(pj.manual_blocks(spec), pg.PAGE).pages
    preview = (tmp_path / "out" / "manual.preview.html").read_text()
    assert preview.count('class="pagebreak"') == pages
    assert f'data-page="{pages}"' in preview


def test_a_command_that_needs_a_key_says_so_before_it_tries(monkeypatch):
    """The offline promise, from the other side: the commands that would spend
    quota name what is missing instead of failing somewhere inside a request."""
    from manualbuilder.superdocs import SuperDocsError

    monkeypatch.delenv("SUPERDOCS_API_KEY", raising=False)
    monkeypatch.setattr("manualbuilder.superdocs.load_dotenv", lambda *a, **k: None)
    monkeypatch.chdir(PROJECT_ROOT)

    with pytest.raises(SuperDocsError, match="SUPERDOCS_API_KEY is not set"):
        cli.main(["export", "--session", "sess_1", "--manual", "doc_1", "--card", "doc_2"])


def test_a_command_that_needs_a_published_pair_says_which_id_is_missing(
    monkeypatch, tmp_path, capsys
):
    """Three ids identify a published pair, and `publish` writes them down so
    nobody has to paste them. Asked to work on a pair that was never published,
    the answer is which id is missing and where it was looked for -- not a
    request to the service with an empty document id in it."""
    monkeypatch.setattr(cli, "OUT", tmp_path / "nothing-here")
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["export"])
    err = capsys.readouterr().err
    assert code == 2
    assert "--session" in err and "Run `publish` first" in err


def test_status_and_verify_need_a_published_pair_before_they_touch_anything(
    monkeypatch, tmp_path, capsys
):
    """Both new commands are free, and both are useless without a published
    pair. Asked to work on one that does not exist they name the missing id
    rather than opening a client and failing inside a request."""
    monkeypatch.setattr(cli, "OUT", tmp_path / "nothing-here")
    monkeypatch.chdir(PROJECT_ROOT)

    for command in ("status", "verify"):
        assert cli.main([command]) == 2
        assert "Run `publish` first" in capsys.readouterr().err


def _published(out: Path) -> None:
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


def test_edit_lets_a_manual_only_fact_through_and_says_so(monkeypatch, tmp_path, capsys):
    """The wiring for `assert_touched_both_or_absent`: a Specifications-table
    edit that only the manual can hold is not refused, and `edit` says why
    the card was skipped instead of silently treating it as fine."""
    from manualbuilder.superdocs import SuperDocs

    old_table = (
        "<table><thead><tr><th>Specification</th><th>Value</th></tr></thead>"
        "<tbody><tr><td>Laser source</td><td>450 nm diode laser</td></tr></tbody></table>"
    )
    new_table = old_table.replace("450 nm", "460 nm")

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def active_jobs(self, session_id):
            return []

        def chat_async(self, message, session_id, document_id=None, **kw):
            return "job_manual" if document_id == "doc_m" else "job_card"

        def wait_for_job(self, job_id):
            if job_id == "job_manual":
                return {
                    "status": "completed",
                    "metadata": {
                        "pending_changes": [
                            {
                                "change_id": "c1",
                                "chunk_id": "chunk_specs",
                                "document_id": "doc_m",
                                "old_html": old_table,
                                "new_html": new_table,
                                "ai_explanation": "updated the specifications",
                            }
                        ]
                    },
                }
            return {"status": "completed", "metadata": {"pending_changes": []}}

        pending_changes = staticmethod(SuperDocs.pending_changes)

        def document_html(self, durable_id):
            assert durable_id == "uuid-c"
            return "<h2>Setup</h2><p>Fit the rails to the base frame.</p>"

    _published(tmp_path / "out")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())

    code, printed = _run(monkeypatch, ["edit", "change the laser source to 460 nm"], capsys)
    assert code == 0
    assert "REFUSED" not in printed
    assert "quick-start card was not required to change" in printed
    assert (tmp_path / "out" / "proposal.json").is_file(), "the manual's change is still recorded"


def test_ask_targets_the_right_document_and_prints_the_answer(monkeypatch, tmp_path, capsys):
    """The manual by default, the card with --document card -- `edit`'s
    always-both shape is exactly what `ask` exists to avoid."""
    calls: list = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def init_session(self, document_ids=None):
            durable_to_doc = {"uuid-m": "doc_m", "uuid-c": "doc_c"}
            return f"fresh_{durable_to_doc[document_ids[0]]}"

        def documents(self, session_id):
            return [{"document_id": session_id.removeprefix("fresh_")}]

        def chat(self, message, session_id, document_id=None, thinking_depth=None, **kw):
            calls.append({"session_id": session_id, "document_id": document_id})
            return {"response": f"answer for {document_id}", "session_id": session_id}

    _published(tmp_path / "out")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())

    code, printed = _run(monkeypatch, ["ask", "what is the max laser power?"], capsys)
    assert code == 0
    assert "answer for doc_m" in printed
    assert calls[-1] == {"session_id": "fresh_doc_m", "document_id": "doc_m"}

    code, printed = _run(monkeypatch, ["ask", "--document", "card", "same question"], capsys)
    assert code == 0
    assert "answer for doc_c" in printed
    assert calls[-1] == {"session_id": "fresh_doc_c", "document_id": "doc_c"}


def test_ask_warns_when_the_turn_also_proposed_changes(monkeypatch, tmp_path, capsys):
    """The synchronous endpoint can propose changes even to a question, and
    those can never be approved -- 'Job is not awaiting approval' is what the
    live service says if you try. `ask` has to say so rather than quietly
    dropping them the way a plain response-only reader would."""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def init_session(self, document_ids=None):
            return "fresh_doc_m"

        def documents(self, session_id):
            return [{"document_id": "doc_m"}]

        def chat(self, message, session_id, document_id=None, thinking_depth=None, **kw):
            return {
                "response": "Sure -- also fixed a typo while I was in there.",
                "session_id": session_id,
                "document_changes": {
                    "pending_changes": [
                        {
                            "change_id": "c1",
                            "chunk_id": "chunk_1",
                            "document_id": document_id,
                            "old_html": "<p>teh</p>",
                            "new_html": "<p>the</p>",
                        }
                    ]
                },
            }

    _published(tmp_path / "out")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())

    code, printed = _run(monkeypatch, ["ask", "any typos in here?"], capsys)
    assert code == 0
    assert "also fixed a typo" in printed
    assert "also proposed 1 change" in printed
    assert "can never be approved" in printed


def test_verify_reports_a_document_that_is_not_what_was_published(monkeypatch, tmp_path, capsys):
    """The wiring that matters, with the network stubbed out: a served document
    pointing at an older drawing has to come back non-zero and name the figure
    -- not print a green summary because the command reached the end."""
    from manualbuilder import projections as pj
    from manualbuilder import verify as vf
    from manualbuilder.spec import load_spec

    from .test_verify import served, urls

    spec = load_spec(PROJECT_ROOT / "spec" / "halyard_m1.yaml")
    images = urls(spec)
    stale = dict(images, **{pj.BREAKDOWN: "https://storage.example/img/old.svg"})
    pages = {
        "manual": served(spec, vf.MANUAL, images),
        "quick-start card": served(spec, vf.CARD, stale),
    }

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            # Keyed by the durable id and nothing else. No session is consulted,
            # so there is no focus for a read to follow to the wrong document --
            # which is the point of reading by id rather than exporting.
            return pages["manual" if durable_id == "uuid-m" else "quick-start card"]

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
                "images": images,
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    # A failing read buys one re-read before it is reported, and the wait
    # between them is real seconds. Nothing here is lagging, so the test does
    # not spend them.
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["verify"])
    printed = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in printed and "breakdown" in printed
    assert "older drawing" in printed
    assert "not what this program recorded publishing" in printed
    assert "the re-read says the same thing" in printed, "a real failure is still a failure"


def test_verify_reads_again_before_it_calls_a_lagging_read_a_failure(monkeypatch, tmp_path, capsys):
    """The false failure this command is most likely to produce, and does not.

    A read taken shortly after an approval can still be the pre-approval
    document -- nine figures still pointing at the previous drawings, on a pair
    that had already been swapped correctly (BUGS #10). Reported as-is that is
    `verify` announcing the service holds something other than what was
    published, about documents that are right. So a failing read is read once
    more, free, before anybody is told anything."""
    from manualbuilder import projections as pj
    from manualbuilder import verify as vf
    from manualbuilder.spec import load_spec

    from .test_verify import served, urls

    spec = load_spec(PROJECT_ROOT / "spec" / "halyard_m1.yaml")
    images = urls(spec)
    stale = dict(images, **{pj.BREAKDOWN: "https://storage.example/img/old.svg"})
    reads: list[str] = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):
            role = vf.MANUAL if durable_id == "uuid-m" else vf.CARD
            reads.append(role)
            # The first read of each document is the pre-approval one; the
            # second is what the service settles on, with nothing done in
            # between. That is the observed behaviour, not a contrived one.
            settled = reads.count(role) > 1
            return served(spec, role, images if settled else stale)

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
                "images": images,
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.setattr(cli.session, "SETTLE_POLL", 0.0)
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["verify"])
    printed = capsys.readouterr().out
    assert code == 0, "a stale first read is not the pair being wrong"
    assert "the first read was stale" in printed, "the re-read has to be visible, not silent"
    assert "0 failed" in printed
    # And what lands in out/served/ is the document as it actually is now.
    assert "old.svg" not in (out / "served" / "quick-start-card.html").read_text()


def test_verify_refuses_a_publication_with_no_durable_ids(monkeypatch, tmp_path):
    """A `published.json` written before durable ids were recorded cannot be
    verified, and has to say so rather than falling back to a session read.

    The fallback is the tempting thing to write and it is the wrong thing: a
    session serves whatever it is focused on, so it would answer -- plausibly,
    and about some other document. Refusing names what is missing instead."""
    from manualbuilder.superdocs import SuperDocsError

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def document_html(self, durable_id):  # pragma: no cover
            raise AssertionError("a read was attempted with no durable id recorded")

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(
        json.dumps(
            {
                "manual_id": "doc_m",
                "card_id": "doc_c",
                "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
                "durable": {},
                "language": "",
                "images": {},
            }
        )
    )

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.chdir(PROJECT_ROOT)

    with pytest.raises(SuperDocsError, match="no durable id recorded"):
        cli.main(["verify"])


def test_publish_clears_what_the_previous_pair_left_behind(monkeypatch, tmp_path, capsys):
    """`out/served/` and `out/export/` are reads of one specific pair, saved
    under filenames that say only "manual" and "quick-start card". A new
    publish used to replace `published.json` and nothing else, so those files
    went on sitting there looking current -- and were read as current, and
    reasoned about, for a pair that no longer existed."""
    from manualbuilder import session

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    out = tmp_path / "out"
    (out / "served").mkdir(parents=True)
    (out / "export").mkdir(parents=True)
    (out / "served" / "manual.html").write_text("<p>the pair before this one</p>")
    (out / "export" / "manual.html").write_text("<p>the pair before this one</p>")
    (out / "proposal.json").write_text("{}")
    (out / "manual.preview.html").write_text("<p>a local render of the spec</p>")

    published = session.Publication(
        manual_id="doc_m",
        card_id="doc_c",
        sessions={"doc_m": "s_manual", "doc_c": "s_card"},
        durable={"doc_m": "uuid-m", "doc_c": "uuid-c"},
        images={"breakdown": "https://cdn.example/breakdown.svg"},
    )
    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.setattr(cli.session, "publish", lambda client, spec, language="": published)

    code, printed = _run(monkeypatch, ["publish"], capsys)

    assert code == 0
    assert not (out / "served").exists() and not (out / "export").exists()
    assert not (out / "proposal.json").exists(), "it names the replaced pair's sessions and jobs"
    assert "cleared" in printed and "served" in printed, "silently deleting files is its own trap"
    # The local render is not a read of any pair -- it is the spec, and `build`
    # owns it. Publishing must not touch it.
    assert (out / "manual.preview.html").is_file()
    assert (out / "published.json").is_file()


def test_edit_says_what_the_turn_said_when_it_proposed_nothing(monkeypatch, tmp_path, capsys):
    """A turn with nothing to change and a turn that asked a question come back
    the same shape. A live run had both documents propose nothing and printed
    only "the turn proposed no changes" -- which is the one case where the
    words are the entire information."""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def active_jobs(self, session_id):
            return []

        def chat_async(self, message, session_id, document_id=None, **kw):
            return f"job_{document_id}"

        def wait_for_job(self, job_id):
            return {
                "status": "completed",
                "metadata": {
                    "pending_changes": [],
                    "response": "Which of the rail steps did you mean?",
                },
            }

        def pending_changes(self, job):
            return []

    _published(tmp_path / "out")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())

    code, printed = _run(monkeypatch, ["edit", "raise the rail torque to 1.6 N·m"], capsys)

    assert code == 0
    assert "the turn proposed no changes" in printed
    assert "Which of the rail steps did you mean?" in printed
