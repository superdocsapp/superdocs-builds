"""Drift detection: what "the document is still clean after 52 weeks" means.

Fourteen invariants, checked against the document's own bytes after every single
week. None of them ask the API whether it did the right thing; all of them
read the document.

They are grouped by what kind of drift they catch:

* STRUCTURE  - headings appear once, in order, unrenamed. This catches the
               classic failure where week 30 quietly grows a second
               "What is next" or renames a section to "Next steps".
* FIDELITY   - the facts in the document are the facts from the week's input,
               verbatim. This catches paraphrase drift, the most dangerous
               kind, because it is invisible to a reader who does not have the
               source in front of them.
* FORMATTING - the table is still bordered, its header still shaded, its rows
               still alternating. This catches the slow bleaching of style
               that happens when a model rewrites a table instead of editing it.
* GROWTH     - the archive accounts for every past week exactly once, stays
               inside its row budget, and contains no row this system cannot
               read. This catches the archive silently becoming unbounded, a
               week's row being quietly dropped, and - the one that got past an
               earlier version - a row whose label is mangled badly enough that
               the coverage check cannot see it at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from superdocs_kit.docdiff import (
    list_items,
    section_html,
    sections,
    table_rows,
    visible_text,
)

from .archive import expected_coverage, parse_existing
from .document import TITLE, expected_archive_rows

RISK_HEADER = ["Risk", "Owner", "Area", "Severity", "Trend"]
ARCHIVE_HEADER = ["Week", "Dates", "Shipped", "Risks carried"]
EXPECTED_H2 = ["What changed", "What is at risk", "What is next", "Archive"]


@dataclass
class Check:
    name: str
    group: str
    ok: bool
    detail: str = ""


@dataclass
class WeekReport:
    week: int
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict:
        return {
            "week": self.week,
            "ok": self.ok,
            "checks": [c.__dict__ for c in self.checks],
        }


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _norm_item(text: str) -> str:
    """Comparison for a bullet or a table cell, with ONE declared tolerance.

    The tolerance: a single trailing full stop is ignored. SuperDocs adds one
    to a bullet perhaps one time in twenty - "…Salvage economy spreadsheet."
    where the input said "…spreadsheet" - and nothing else about the bullet
    differs. Failing the week for a full stop would mean spending a repair
    operation to move a period, and would drown the signal that this check
    exists for: a bullet whose CONTENT is wrong.

    It is declared here rather than quietly folded into _norm because a
    tolerance a reader cannot see is indistinguishable from a bug. Everything
    else is still compared exactly: wording, ordering, count, and every other
    character.
    """
    return _norm(text).rstrip(".")


def check_week(
    html: str, week: dict, published_weeks: set[int] | None = None
) -> WeekReport:
    """`published_weeks` is the set of weeks that actually reached the document
    before this one. It is NOT always {1..N-1}: if a week failed verification
    twice and was rolled back, it was never published and its row was never
    archived, so demanding it would make the invariant unsatisfiable forever
    after. The runner passes what really happened; the default keeps the strict
    reading for anyone checking a clean run offline."""
    rep = WeekReport(week=week["week"])
    add = lambda n, g, ok, d="": rep.checks.append(Check(n, g, ok, d))  # noqa: E731

    secs = sections(html)
    h1s = [s for s in secs if s.level == 1]
    h2s = [s.heading.strip() for s in secs if s.level == 2]

    # ---- STRUCTURE -------------------------------------------------
    add("title unchanged", "structure",
        len(h1s) == 1 and _norm(h1s[0].heading) == _norm(TITLE),
        f"found {[s.heading for s in h1s]}")
    add("four H2 sections, correct names, correct order", "structure",
        h2s == EXPECTED_H2, f"found {h2s}")
    add("no duplicated section", "structure",
        len(h2s) == len(set(h2s)), f"found {h2s}")

    # ---- FIDELITY ---------------------------------------------------
    status = _norm(visible_text(html[: html.find("<h2") if "<h2" in html else 400]))
    want_status = _norm(f"Week {week['week']} · {week['dates']} · Phase: {week['phase']}")
    add("status line matches the week", "fidelity",
        want_status in status, f"wanted '{want_status}'")

    changed = list_items(section_html(html, "What changed"))
    add("'What changed' bullets are verbatim", "fidelity",
        [_norm_item(x) for x in changed] == [_norm_item(x) for x in week["shipped"]],
        f"got {changed}")

    nxt = list_items(section_html(html, "What is next"))
    add("'What is next' bullets are verbatim", "fidelity",
        [_norm_item(x) for x in nxt] == [_norm_item(x) for x in week["next"]],
        f"got {nxt}")

    risk_frag = section_html(html, "What is at risk")
    rows = table_rows(risk_frag)
    header = rows[0] if rows else []
    data = rows[1:] if rows else []
    want = [[r["risk"], r["owner"], r["area"], r["severity"], r["trend"]] for r in week["risks"]]
    add("risk table header intact", "structure",
        [_norm(c) for c in header] == [_norm(c) for c in RISK_HEADER], f"got {header}")
    add("risk table rows match the week exactly", "fidelity",
        [[_norm_item(c) for c in r] for r in data] == [[_norm_item(c) for c in r] for r in want],
        f"got {len(data)} rows, wanted {len(want)}")

    # ---- FORMATTING -------------------------------------------------
    styled = (
        "border-collapse" in risk_frag
        and re.search(r"background-color:\s*#263238", risk_frag, re.I) is not None
    )
    alternating = re.search(r"background-color:\s*#eceff1", risk_frag, re.I) is not None
    add("risk table keeps borders and header shading", "formatting", styled)
    add("risk table keeps alternating row shading", "formatting",
        alternating or len(data) < 2, "no #eceff1 cell found")

    # ---- GROWTH ------------------------------------------------------
    # Counting rows was the first version of this check and it was too weak:
    # it passed a week in which the model had duplicated the header row into
    # the table body and dropped a real week's row - the count was right and
    # the content was wrong. Coverage is the honest invariant.
    arch = parse_existing(html)
    covered: list[int] = [w for row in arch for w in sorted(row.covered_weeks)]
    want = expected_coverage(week["week"]) if published_weeks is None else set(published_weeks)
    dupes = sorted({w for w in covered if covered.count(w) > 1})
    add("archive covers every past week exactly once", "growth",
        set(covered) == want and not dupes,
        f"covered {sorted(set(covered))}, wanted {sorted(want)}"
        + (f", duplicated {dupes}" if dupes else ""))

    detail, rollups = expected_archive_rows(week["week"])
    add("archive stays bounded (growth policy)", "growth",
        len(arch) <= detail + rollups or week["week"] <= 1,
        f"{len(arch)} rows; policy allows {detail} detail + {rollups} rolled up")

    all_rows = table_rows(section_html(html, "Archive"))
    stray_header = any(
        [_norm(c) for c in r] == [_norm(c) for c in ARCHIVE_HEADER] for r in all_rows[1:]
    )
    add("no header row copied into the archive body", "structure", not stray_header)

    # A CHECK THAT IGNORES WHAT IT CANNOT PARSE IS NOT A CHECK.
    #
    # `parse_existing` drops any row it does not recognise, which is right for
    # PLANNING (a junk row should not be propagated into next week's archive)
    # and was silently wrong for VERIFYING. It cost a real week: the model wrote
    # the label as "1" instead of "Week 1", the coverage check could not see the
    # row at all, the repair added a second row with the correct label, and the
    # week passed carrying BOTH - a visible duplicate in the reader's document,
    # under an invariant whose name is "covers every past week exactly once".
    #
    # So the archive body is now checked twice: for what it covers, and for
    # whether every row in it is a row this system understands. The second one
    # closes the whole class - a mangled label, a merged row, a stray sentence -
    # rather than the one label that surfaced it.
    unreadable = [
        r[0] for r in all_rows[1:]
        if len(r) >= 4 and not _recognisable_archive_label(r[0])
    ]
    add("every archive row is a row this system can read", "growth",
        not unreadable or week["week"] <= 1,
        f"unreadable labels: {unreadable[:4]}")

    return rep


def _recognisable_archive_label(label: str) -> bool:
    """A row the archive planner would carry forward: 'Week 7', 'Weeks 3-6 …'.

    The seed placeholder ('-') is exempt only at week 1, which is why the check
    above is skipped there; from week 2 the placeholder must have been replaced.
    """
    from .archive import _ROLLUP_RE, _WEEK_RE

    text = (label or "").strip()
    return bool(_WEEK_RE.match(text) or _ROLLUP_RE.match(text))


def drift_table(reports: list[WeekReport]) -> str:
    """The one artefact that answers 'did drift appear?'."""
    groups = ["structure", "fidelity", "formatting", "growth"]
    lines = ["| Week | " + " | ".join(g for g in groups) + " | verdict |",
             "|---|" + "---|" * (len(groups) + 1)]
    for rep in reports:
        cells = []
        for g in groups:
            gc = [c for c in rep.checks if c.group == g]
            bad = [c for c in gc if not c.ok]
            cells.append("ok" if not bad else f"**{len(bad)} FAIL**")
        lines.append(f"| {rep.week} | " + " | ".join(cells) +
                     f" | {'clean' if rep.ok else 'DRIFT'} |")
    return "\n".join(lines)
