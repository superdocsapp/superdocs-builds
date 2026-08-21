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


# ------------------------------------------------------------------ the prompt


def test_the_prompt_is_shown_in_full(capsys):
    """SuperDocs writes the prose; what this tool controls is the brief.

    A reviewer who sees only the proposed diff is reviewing the answer without the
    question, so the instruction is printed whole — for the same reason the gate refuses
    to truncate proposed text.
    """
    from afteraction.cli import _echo_prompt

    instruction = "\n".join(f"line {n} of the brief" for n in range(40))
    _echo_prompt(instruction)
    printed = capsys.readouterr().out

    assert "prompt sent to SuperDocs (40 lines)" in printed
    for n in range(40):
        assert f"line {n} of the brief" in printed


def test_prompts_are_off_by_default_and_on_for_the_interactive_gate(capsys):
    """A timeline instruction runs to a couple of hundred lines: useful when reviewing
    what was asked, noise when watching a build finish. Someone approving each change by
    hand is exactly the person who needs the question as well as the answer."""
    from afteraction.cli import _reporter

    _reporter(False)("prompt", "a long instruction")
    assert "a long instruction" not in capsys.readouterr().out

    _reporter(True)("prompt", "a long instruction")
    assert "a long instruction" in capsys.readouterr().out


def test_other_stages_still_report_when_prompts_are_off(capsys):
    from afteraction.cli import _reporter

    _reporter(False)("verify", "37/37 claims traced")
    assert "37/37 claims traced" in capsys.readouterr().out
