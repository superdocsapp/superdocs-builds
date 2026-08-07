"""Record/replay (so the suite needs no key) and the archive growth policy.

The archive test is the one worth reading. It simulates all fifty-two weeks of
growth offline, feeding each week's planned rows back in as the next week's
input document, and asserts the two properties that actually matter: every past
week is accounted for exactly once, and the table never grows without bound.
Getting that wrong on the live API would have cost fifty-two operations to find
out; here it costs milliseconds.
"""

import json

import pytest

from superdocs_kit.errors import ApiError, ReplayMiss
from superdocs_kit.transport import (
    RecordingTransport,
    ReplayTransport,
    Response,
    Transport,
    request_key,
)
from weekly_digest.archive import (
    AUTHOR,
    expected_coverage,
    parse_existing,
    plan_rows,
    render_instruction_block,
)
from weekly_digest.document import (
    ARCHIVE_MAX_DETAIL_ROWS,
    ARCHIVE_ROLLUP_SIZE,
    TITLE,
    archive_plan,
    seed_html,
)


class FakeTransport(Transport):
    def __init__(self, payload, status=200):
        self.payload, self.status, self.calls = payload, status, []

    def request(self, method, path, body=None, *, timeout=600.0):
        self.calls.append((method, path, body))
        if self.status >= 400:
            raise ApiError(self.status, path, json.dumps(self.payload))
        return Response(self.status, self.payload, 0.1)


# --------------------------------------------------------------- transport
def test_record_then_replay_needs_no_network_and_no_key(tmp_path):
    inner = FakeTransport({"response": "ok", "usage": {"ops_charged": 1}})
    rec = RecordingTransport(inner, tmp_path / "cass")
    rec.request("POST", "/v1/chat", {"session_id": "s1", "message": "hello"})

    replay = ReplayTransport(tmp_path / "cass")
    out = replay.request("POST", "/v1/chat", {"session_id": "DIFFERENT", "message": "hello"})
    assert out.json_body["response"] == "ok"


def test_session_id_is_excluded_from_the_cassette_key():
    """Otherwise every replay would miss, because session ids are per-run."""
    a = request_key("POST", "/v1/chat", {"session_id": "a", "message": "m"})
    b = request_key("POST", "/v1/chat", {"session_id": "b", "message": "m"})
    assert a == b
    c = request_key("POST", "/v1/chat", {"session_id": "a", "message": "different"})
    assert a != c


def test_a_replay_miss_names_the_fix(tmp_path):
    (tmp_path / "cass").mkdir()
    replay = ReplayTransport(tmp_path / "cass")
    with pytest.raises(ReplayMiss) as exc:
        replay.request("POST", "/v1/chat", {"message": "never recorded"})
    assert "SUPERDOCS_RECORD" in str(exc.value)


def test_recorded_fixtures_never_contain_a_key(tmp_path):
    inner = FakeTransport({"mcp_setup": {"cmd": "--header 'Authorization: Bearer sk_deadbeef1234567890'"}})
    rec = RecordingTransport(inner, tmp_path / "cass")
    rec.request("POST", "/v1/agents/signup", {"api_key": "sk_deadbeef1234567890"})
    blob = "".join(p.read_text() for p in (tmp_path / "cass").glob("*.json"))
    assert "deadbeef1234567890" not in blob


def test_binary_responses_survive_the_round_trip(tmp_path):
    class Bin(Transport):
        def request(self, method, path, body=None, *, timeout=600.0):
            return Response(200, None, 0.1, content=b"# Title\n", content_type="text/markdown")

    rec = RecordingTransport(Bin(), tmp_path / "cass")
    rec.request("POST", "/v1/documents/export", {"format": "markdown"})
    out = ReplayTransport(tmp_path / "cass").request(
        "POST", "/v1/documents/export", {"format": "markdown"})
    assert out.text() == "# Title\n"


# ----------------------------------------------------------------- archive
def _render(rows):
    body = "".join(
        f"<tr><td>{r.label}</td><td>{r.dates}</td><td>{r.shipped}</td><td>{r.risks}</td></tr>"
        for r in rows
    )
    return ('<h1>D</h1><h2>Archive</h2><table><thead><tr><th>Week</th><th>Dates</th>'
            f'<th>Shipped</th><th>Risks carried</th></tr></thead><tbody>{body}</tbody></table>')


def test_fifty_two_weeks_of_archive_growth_offline(weeks):
    """Every past week accounted for exactly once, table never unbounded."""
    html = _render([])
    html = html.replace("<tbody></tbody>",
                        "<tbody><tr><td>-</td><td>-</td><td>Digest opened. "
                        "No prior weeks.</td><td>-</td></tr></tbody>")
    biggest = 0
    rollup_weeks = []
    for n in range(2, 53):
        rows, rollup = plan_rows(html, weeks[n - 2])
        if rollup:
            rollup_weeks.append(n)
        for r in rows:                       # stand in for the model's prose
            if r.shipped == AUTHOR:
                r.shipped, r.risks = f"summary {r.label}", "risks"
        covered = [w for r in rows for w in sorted(r.covered_weeks)]
        assert set(covered) == expected_coverage(n), f"week {n} coverage"
        assert len(covered) == len(set(covered)), f"week {n} covers a week twice"
        biggest = max(biggest, len(rows))
        html = _render(rows)

    assert biggest <= ARCHIVE_MAX_DETAIL_ROWS + 13, f"archive grew to {biggest} rows"
    assert rollup_weeks[0] == ARCHIVE_MAX_DETAIL_ROWS + 2
    assert all(b - a == ARCHIVE_ROLLUP_SIZE for a, b in zip(rollup_weeks, rollup_weeks[1:]))


def test_archive_drops_a_header_row_that_leaked_into_the_body():
    """Observed live: the model copied the header row into the table body.
    Restating the archive each week repairs it for free."""
    html = ('<h2>Archive</h2><table><thead><tr><th>Week</th><th>Dates</th><th>Shipped</th>'
            '<th>Risks carried</th></tr></thead><tbody>'
            '<tr><td>Week</td><td>Dates</td><td>Shipped</td><td>Risks carried</td></tr>'
            '<tr><td>Week 1</td><td>d1</td><td>s</td><td>r</td></tr></tbody></table>')
    assert [r.label for r in parse_existing(html)] == ["Week 1"]


def test_archive_deduplicates_a_week_that_appears_twice():
    html = ('<h2>Archive</h2><table><thead><tr><th>Week</th><th>Dates</th><th>Shipped</th>'
            '<th>Risks carried</th></tr></thead><tbody>'
            '<tr><td>Week 2</td><td>d2</td><td>newest</td><td>r</td></tr>'
            '<tr><td>Week 2</td><td>d2</td><td>stale</td><td>r</td></tr>'
            '<tr><td>Week 1</td><td>d1</td><td>s</td><td>r</td></tr></tbody></table>')
    rows, _ = plan_rows(html, {"week": 3, "dates": "d3"})
    labels = [r.label for r in rows]
    assert labels == ["Week 3", "Week 2", "Week 1"]


def test_rollup_instruction_lists_the_rows_being_folded(weeks):
    html = _render([])
    for n in range(2, 12):
        rows, rollup = plan_rows(html, weeks[n - 2])
        for r in rows:
            if r.shipped == AUTHOR:
                r.shipped, r.risks = f"summary {r.label}", "risks"
        if rollup:
            block = render_instruction_block(rows, rollup)
            assert "rolled up" in block
            # the rollup row must name every row it replaces, and say to delete them
            assert block.count("'Week ") >= ARCHIVE_ROLLUP_SIZE
            assert "REPLACES" in block and "Delete those rows." in block
            # and the block must stay short: it is what pushed the instruction
            # past the length where the model started dropping later steps
            assert len(block) < 1200, f"archive block grew to {len(block)} chars"
            return
        html = _render(rows)
    pytest.fail("no rollup fired in the first ten weeks")


def test_a_mangled_archive_label_fails_the_week_instead_of_being_ignored(weeks):
    """The regression that closed a hole in the checker itself.

    Live, week 2 came back with the archive label written as "1" instead of
    "Week 1". `parse_existing` cannot read that row, so the coverage check could
    not see it, the repair turn added a *second* row with the right label, and
    the week passed its invariants carrying a visible duplicate. A check that
    silently ignores what it cannot parse is not a check.

    Both shapes must now fail: the mangled row on its own, and the mangled row
    sitting next to the correct one - the exact document the live run produced.
    """
    from weekly_digest.verify import check_week

    def doc(archive_rows: str) -> str:
        w = weeks[1]
        bullets = "".join(f"<li>{s}</li>" for s in w["shipped"])
        nxt = "".join(f"<li>{s}</li>" for s in w["next"])
        risks = "".join(
            "<tr>" + "".join(
                f'<td style="background-color:#eceff1">{r[k]}</td>'
                for k in ("risk", "owner", "area", "severity", "trend")
            ) + "</tr>" for r in w["risks"]
        )
        return (
            f"<h1>{TITLE}</h1><p>Week {w['week']} &middot; {w['dates']} &middot; "
            f"Phase: {w['phase']}</p>"
            f"<h2>What changed</h2><ul>{bullets}</ul>"
            '<h2>What is at risk</h2><table style="border-collapse:collapse">'
            '<thead><tr><th style="background-color:#263238">Risk</th>'
            '<th>Owner</th><th>Area</th><th>Severity</th><th>Trend</th></tr></thead>'
            f"<tbody>{risks}</tbody></table>"
            f"<h2>What is next</h2><ul>{nxt}</ul>"
            "<h2>Archive</h2><table><thead><tr><th>Week</th><th>Dates</th>"
            "<th>Shipped</th><th>Risks carried</th></tr></thead>"
            f"<tbody>{archive_rows}</tbody></table>"
        )

    good = "<tr><td>Week 1</td><td>d1</td><td>s</td><td>r</td></tr>"
    mangled = "<tr><td>1</td><td>d1</td><td>s</td><td>r</td></tr>"
    named = "every archive row is a row this system can read"

    clean = check_week(doc(good), weeks[1], {1})
    assert [c.ok for c in clean.checks if c.name == named] == [True]

    for archive in (mangled, mangled + good, good + mangled):
        rep = check_week(doc(archive), weeks[1], {1})
        assert not rep.ok, f"a document with a mangled archive label passed: {archive}"
        assert named in [c.name for c in rep.failures]


def test_week_one_seed_is_well_formed(weeks):
    html = seed_html(weeks[0])
    assert html.count("<h2") == 4 and "data-chunk-id" not in html
    assert archive_plan(1).add_row_for_week is None
