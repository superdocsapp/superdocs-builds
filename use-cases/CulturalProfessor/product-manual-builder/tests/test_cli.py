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


def test_check_fails_and_says_where_when_a_locale_runs_long(
        monkeypatch, tmp_path, capsys):
    """The wiring that matters. A locale is lengthened until it repaginates, and
    `check` has to come back non-zero with the block named -- not with a
    traceback, and not with `ok`."""
    locales = tmp_path / "locales"
    locales.mkdir()
    raw = yaml.safe_load((PROJECT_ROOT / "locales" / "de.yaml").read_text())
    for warning in raw["warnings"].values():
        warning["body"] = " ".join([warning["body"]] * 3)
    (locales / "de.yaml").write_text(
        yaml.safe_dump(raw, allow_unicode=True, sort_keys=False))

    monkeypatch.setattr(cli, "LOCALES", locales)
    code, out = _run(monkeypatch, ["check"], capsys)

    assert code == 1
    assert "FAIL" in out
    assert "would repaginate" in out
    assert "safety:warning:" in out, "the report must name the block that moved"


def test_build_writes_a_document_per_language_and_its_diagrams(
        monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    code, out = _run(monkeypatch, ["build"], capsys)
    assert code == 0

    written = {path.name for path in (tmp_path / "out").iterdir()}
    for name in ("manual.html", "quickstart.html", "manual.de.html",
                 "manual.fr.html", "manual.preview.html"):
        assert name in written

    # The drawings are per language too, not the English ones reused.
    assert {"breakdown.svg", "breakdown.de.svg", "breakdown.fr.svg"} <= written
    english = (tmp_path / "out" / "breakdown.svg").read_text()
    german = (tmp_path / "out" / "breakdown.de.svg").read_text()
    assert english != german
    assert "Grundrahmen" in german


def test_the_preview_marks_every_page_the_layout_found(monkeypatch, tmp_path,
                                                       capsys):
    """The preview is what makes the pagination claim something you can look at.
    If it drew fewer rules than there are pages it would be a picture of a
    different document."""
    from manualbuilder import paginate as pg, projections as pj
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
        cli.main(["export", "--session", "sess_1",
                  "--manual", "doc_1", "--card", "doc_2"])


def test_a_command_that_needs_a_published_pair_says_which_id_is_missing(
        monkeypatch, tmp_path, capsys):
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
        monkeypatch, tmp_path, capsys):
    """Both new commands are free, and both are useless without a published
    pair. Asked to work on one that does not exist they name the missing id
    rather than opening a client and failing inside a request."""
    monkeypatch.setattr(cli, "OUT", tmp_path / "nothing-here")
    monkeypatch.chdir(PROJECT_ROOT)

    for command in ("status", "verify"):
        assert cli.main([command]) == 2
        assert "Run `publish` first" in capsys.readouterr().err


def test_verify_reports_a_document_that_is_not_what_was_published(
        monkeypatch, tmp_path, capsys):
    """The wiring that matters, with the network stubbed out: a served document
    pointing at an older drawing has to come back non-zero and name the figure
    -- not print a green summary because the command reached the end."""
    from manualbuilder import projections as pj, verify as vf
    from manualbuilder.spec import load_spec

    from .test_verify import served, urls

    spec = load_spec(PROJECT_ROOT / "spec" / "halyard_m1.yaml")
    images = urls(spec)
    stale = dict(images, **{pj.BREAKDOWN: "https://storage.example/img/old.svg"})
    pages = {"manual": served(spec, vf.MANUAL, images),
             "quick-start card": served(spec, vf.CARD, stale)}

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *exc): return False

        def documents(self, session_id):
            # Both sessions still hold what they were published holding, so
            # nothing gets re-bound and the export goes ahead.
            return [{"document_id":
                     "doc_m" if session_id == "s_manual" else "doc_c"}]

        def export_bytes(self, session_id, fmt, filename=None):
            # One session per document, so the session is what picks the page.
            return pages["manual" if session_id == "s_manual"
                         else "quick-start card"].encode("utf-8")

    out = tmp_path / "out"
    out.mkdir()
    (out / "published.json").write_text(json.dumps({
        "manual_id": "doc_m", "card_id": "doc_c",
        "sessions": {"doc_m": "s_manual", "doc_c": "s_card"},
        "durable": {}, "language": "", "images": images}))

    monkeypatch.setattr(cli, "OUT", out)
    monkeypatch.setattr(cli, "_client", lambda: FakeClient())
    monkeypatch.chdir(PROJECT_ROOT)

    code = cli.main(["verify"])
    printed = capsys.readouterr().out
    assert code == 1
    assert "FAIL" in printed and "breakdown" in printed
    assert "older drawing" in printed
    assert "not what this program recorded publishing" in printed
