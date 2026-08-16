"""The review screen a person actually looks at.

Both tests here come from real failures. The gate truncated proposed text, so a
reviewer was being asked to approve an edit they could not fully see; and printing a
change whose text contained a typographic quote crashed outright on a Windows console.
"""

from __future__ import annotations

from unittest import mock

import pytest

from afteraction.cli import _interactive_gate, _readable
from afteraction.client import ProposedChange


def _change(new_html: str, old_html: str = "<p>Placeholder for observed statements.</p>"):
    return ProposedChange(
        change_id="ch_1",
        operation="edit",
        chunk_id="c1",
        old_html=old_html,
        new_html=new_html,
        explanation="Drafted 3 observed statement(s).",
    )


def test_the_whole_proposed_text_is_shown_not_a_prefix(capsys):
    """A gate that truncates is asking for approval of text the reviewer cannot see."""
    tail = "The final sentence carries the citation [EL-0030]."
    body = "<p>" + ("A long observed statement about the restoration. " * 40) + tail + "</p>"

    with mock.patch("typer.confirm", return_value=True):
        approved, reason = _interactive_gate(_change(body))

    printed = capsys.readouterr().out
    assert approved and reason is None
    assert tail in printed.replace("\n", " ").replace("      ", "")
    assert "EL-0030" in printed


def test_typographic_characters_do_not_crash_the_review(capsys):
    """The report's own prose contains curly quotes and em dashes; a cp1252 console
    raised UnicodeEncodeError on them mid-review."""
    body = "<p>Communication CC-A06 (press, “Briefing to local media”) — no log entry [no record].</p>"

    with mock.patch("typer.confirm", return_value=True):
        _interactive_gate(_change(body))

    assert "CC-A06" in capsys.readouterr().out


def test_rejecting_returns_the_reason_for_the_model(capsys):
    with mock.patch("typer.confirm", return_value=False), mock.patch(
        "typer.prompt", return_value="figure needs checking against the log"
    ):
        approved, reason = _interactive_gate(_change("<p>Something questionable.</p>"))

    assert approved is False
    assert reason == "figure needs checking against the log"


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>One.</p><p>Two.</p>", "One.\nTwo."),
        ('<img src="x.png" alt="Restoration curve" />', "[image: Restoration curve]"),
        ("<table><tr><td>a</td><td>b</td></tr></table>", "a | b |"),
        (None, "(nothing)"),
    ],
)
def test_html_is_rendered_as_readable_prose(html, expected):
    assert _readable(html).strip() == expected
