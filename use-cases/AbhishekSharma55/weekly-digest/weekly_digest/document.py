"""The digest document itself: the seed, and the archive growth policy.

The seed is deliberately *formatted* - a bordered, shaded, alternating-row
risk table, a coloured status line, a specific font stack. Plain paragraphs
would make "formatting is preserved" an untestable claim. With this seed,
fifty-two edits later either the shading survived or it did not, and the
exported .docx says which.

The seed is uploaded verbatim (``/v1/documents/upload-base64``), never
authored by the model, so week 0 is a known, byte-exact starting point.
"""

from __future__ import annotations

from dataclasses import dataclass

STUDIO = "Vantage Nine Studios"
TITLE = "Nebula Drift - Weekly Production Digest"

STANDING_SECTIONS = ["What changed", "What is at risk", "What is next"]
ARCHIVE_SECTION = "Archive"

# Archive growth policy. Kept here as data, not scattered through the runner,
# because "how the archive stays navigable" is a decision a reader will want
# to find in one place and change without touching the loop.
ARCHIVE_MAX_DETAIL_ROWS = 8   # detailed week rows kept verbatim
ARCHIVE_ROLLUP_SIZE = 4       # oldest N detail rows folded into one summary row

_TABLE_STYLE = (
    "width:100%;border-collapse:collapse;border:1px solid #37474f;"
    "font-family:Inter,Calibri,Arial,sans-serif;font-size:10pt"
)
_TH = (
    "border:1px solid #37474f;background-color:#263238;color:#ffffff;"
    "padding:6px 8px;text-align:left;font-weight:bold"
)
_TD = "border:1px solid #90a4ae;padding:6px 8px;vertical-align:top"
_TD_ALT = _TD + ";background-color:#eceff1"


def seed_html(first_week: dict) -> str:
    """Week 1 of the digest, rendered exactly - no model involved."""
    risk_rows = "".join(
        f"<tr><td style=\"{_td(i)}\">{_esc(r['risk'])}</td>"
        f"<td style=\"{_td(i)}\">{_esc(r['owner'])}</td>"
        f"<td style=\"{_td(i)}\">{_esc(r['area'])}</td>"
        f"<td style=\"{_td(i)}\">{_esc(r['severity'])}</td>"
        f"<td style=\"{_td(i)}\">{_esc(r['trend'])}</td></tr>"
        for i, r in enumerate(first_week["risks"])
    )
    shipped = "".join(f"<li>{_esc(s)}</li>" for s in first_week["shipped"])
    nxt = "".join(f"<li>{_esc(s)}</li>" for s in first_week["next"])

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{_esc(TITLE)}</title></head>
<body style="font-family:Inter,Calibri,Arial,sans-serif;color:#212121">
<h1 style="color:#1a237e;border-bottom:3px solid #1a237e;padding-bottom:6px">{_esc(TITLE)}</h1>
<p style="background-color:#e8eaf6;padding:8px 10px;border-left:4px solid #3949ab">
<strong>Week {first_week['week']} &middot; {_esc(first_week['dates'])} &middot; Phase: {_esc(first_week['phase'])}</strong>
<br><span style="color:#546e7a;font-size:9pt">{_esc(STUDIO)} &middot; internal &middot; standing document, edited in place every Monday</span></p>

<h2 style="color:#1a237e">What changed</h2>
<ul>{shipped}</ul>

<h2 style="color:#1a237e">What is at risk</h2>
<table style="{_TABLE_STYLE}">
<thead><tr>
<th style="{_TH}">Risk</th><th style="{_TH}">Owner</th><th style="{_TH}">Area</th>
<th style="{_TH}">Severity</th><th style="{_TH}">Trend</th>
</tr></thead>
<tbody>{risk_rows}</tbody>
</table>

<h2 style="color:#1a237e">What is next</h2>
<ul>{nxt}</ul>

<h2 style="color:#1a237e">Archive</h2>
<p style="color:#546e7a;font-size:9pt">Newest first. Detail rows older than
{ARCHIVE_MAX_DETAIL_ROWS} weeks are folded into a single rolled-up row so this
section stays readable at 52 weeks.</p>
<table style="{_TABLE_STYLE}">
<thead><tr>
<th style="{_TH}">Week</th><th style="{_TH}">Dates</th>
<th style="{_TH}">Shipped</th><th style="{_TH}">Risks carried</th>
</tr></thead>
<tbody>
<tr><td style="{_TD}">-</td><td style="{_TD}">-</td>
<td style="{_TD}">Digest opened. No prior weeks.</td><td style="{_TD}">-</td></tr>
</tbody>
</table>
</body></html>
"""


def _td(i: int) -> str:
    return _TD_ALT if i % 2 else _TD


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


@dataclass
class ArchivePlan:
    """What the archive should do this week."""

    add_row_for_week: int | None
    rollup_from: int | None = None   # inclusive week number
    rollup_to: int | None = None


def archive_plan(week: int) -> ArchivePlan:
    """Decide, purely from the week number, what happens to the archive.

    Week N archives week N-1. Once the number of detail rows would exceed
    ARCHIVE_MAX_DETAIL_ROWS, the oldest ARCHIVE_ROLLUP_SIZE of them are folded
    into one row *in the same operation* - so keeping the archive navigable
    costs zero extra operations, which is the whole reason the policy is
    shaped this way.
    """
    if week <= 1:
        return ArchivePlan(add_row_for_week=None)

    archived_weeks = week - 1               # weeks 1..week-1 have been archived
    detail_rows = archived_weeks
    rolled = 0
    while detail_rows > ARCHIVE_MAX_DETAIL_ROWS:
        detail_rows -= ARCHIVE_ROLLUP_SIZE
        rolled += ARCHIVE_ROLLUP_SIZE

    plan = ArchivePlan(add_row_for_week=week - 1)
    # A rollup fires on exactly the week the threshold is first crossed.
    prev_rolled = 0
    prev_detail = archived_weeks - 1
    while prev_detail > ARCHIVE_MAX_DETAIL_ROWS:
        prev_detail -= ARCHIVE_ROLLUP_SIZE
        prev_rolled += ARCHIVE_ROLLUP_SIZE
    if rolled > prev_rolled:
        plan.rollup_from = prev_rolled + 1
        plan.rollup_to = rolled
    return plan


def expected_archive_rows(week: int) -> tuple[int, int]:
    """(detail_rows, rollup_rows) the archive should hold after week N's edit.
    Used as an invariant in verification, not as an instruction to the model."""
    if week <= 1:
        return (0, 0)
    detail = week - 1
    rolled = 0
    while detail > ARCHIVE_MAX_DETAIL_ROWS:
        detail -= ARCHIVE_ROLLUP_SIZE
        rolled += 1
    return (detail, rolled)


# ---------------------------------------------------------------------------
# Exact replacement HTML for the factual sections.
#
# WHY THIS EXISTS, because it is the decision most worth defending.
#
# The weekly instruction originally DESCRIBED what the standing sections should
# contain: "replace all bullets with exactly these four". Measured over the
# first seven weeks, that was read as *append* often enough to matter - week 7
# came back with the five old bullets kept and the four new ones added, nine
# where four were asked for. Rewording it three times ("delete the list, then
# write a new one", "the section must end with exactly four bullets - not
# more") reduced the rate and did not remove it.
#
# So the factual sections are now handed over as literal HTML. The model is not
# asked to author, re-type or reason about a fact; it is asked to splice a known
# fragment into the right place in a formatted document, which is exactly what a
# document editor is for.
#
# This is the build's thesis at its purest - FACTS ARE TRANSPORTED, PROSE IS
# GENERATED - and it is a narrowing of the model's job, done on evidence. The
# model still WRITES every archive summary and every quarterly rollup, which is
# the part that genuinely needs a model. What it no longer has to do is go and
# find the source: the outgoing week's bullets and risks are handed to the
# archive step in quotes, because asking a model to summarise "the bullets
# currently under 'What changed'" in the same turn that replaces those bullets
# produced rows describing the wrong week, three times in seven (bugs.md M7).
# And because the alternating row shading is generated here rather than hoped
# for, formatting preservation stops depending on the model noticing.


def bullets_html(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"


def risk_rows_html(risks: list[dict]) -> str:
    """The table BODY rows only, with the seed's alternating shading preserved."""
    return "".join(
        f'<tr><td style="{_td(i)}">{_esc(r["risk"])}</td>'
        f'<td style="{_td(i)}">{_esc(r["owner"])}</td>'
        f'<td style="{_td(i)}">{_esc(r["area"])}</td>'
        f'<td style="{_td(i)}">{_esc(r["severity"])}</td>'
        f'<td style="{_td(i)}">{_esc(r["trend"])}</td></tr>'
        for i, r in enumerate(risks)
    )
