import contextlib
import io
import json as _json

import pytest

from clausekeeper import cli, db, discover, ingest, linking
from clausekeeper.library import LIBRARY_PATH, load_library

from conftest import CORPUS, FIXTURES as FIXTURES_DIR, client_for, seeded  # noqa: F401,E501
from conftest import seeded_conn  # noqa: F401


def _all_clauses():
    return load_library(LIBRARY_PATH)


def _no_match_roster_script(search_response, search_usage):
    roster = {"documents": [
        {"document_id": f"doc_p0{n}", "html":
         '<h1>proc</h1><div data-chunk-id="cx"><h2>Banana protocol</h2>'
         '<p>body</p></div>'}
        for n in (2, 3, 4, 5, 6)] + [
        {"document_id": "doc_qm01", "html":
         '<h1>manual</h1><div data-chunk-id="cx9"><h2>Widget calibration</h2>'
         '<p>body</p></div>'}]}
    return [
        {"method": "GET", "path": "/v1/sessions/ck-demo-01/documents",
         "params": {"include_html": "true"}, "responses": [roster]},
        {"method": "POST", "path": "/v1/chat/async",
         "responses": [{"job_id": "job_disc_u", "status": "pending"}]},
        {"method": "GET", "path": "/v1/jobs/{id}",
         "responses": [{"job_id": "job_disc_u", "status": "completed",
                        "result": {"response": search_response,
                                   "usage": search_usage}}]},
    ]


def test_discover_e2e_happy_path_with_search_fallback(tmp_path, monkeypatch,
                                                      capsys):
    root = str(tmp_path / "disc.db")
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "init_link.json"))
    cli.main(["--db", root, "init", "--corpus", str(CORPUS)])
    monkeypatch.setenv("CK_FIXTURE",
                       str(FIXTURES_DIR / "discover_link.json"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["--db", root, "link", "--discover"])
    text = out.getvalue()
    assert "DISCOVER pass (opt-in)" in text
    assert "local match resolved 12/27" in text
    assert "[search] charged 1 op (was_billable=true, ops_charged=1)" in text
    assert "search resolved 15/15 remaining clauses" in text
    assert "SHORTLIST (candidates found before mapping)" in text
    assert "linked NM-QM-01-quality-manual: 2 clauses covered" in text
    assert ("ops charged this run: 7 (mapping 6 + discover search 1)"
            in text)
    conn = db.connect(root)
    rows = conn.execute("SELECT * FROM shortlists").fetchall()
    assert len(rows) == 27
    sources = {r["source"] for r in rows}
    assert sources == {"local", "search"}
    search_rows = [r for r in rows if r["source"] == "search"]
    assert {r["clause_id"] for r in search_rows} >= {"9.2", "9.3"}
    assert all(r["discovered_at"] for r in rows)
    usage = conn.execute(
        "SELECT COUNT(*) c FROM usage_log WHERE ops_charged = 1"
        ).fetchone()["c"]
    assert usage == 7
    conn.close()


def test_search_reply_embedded_json_trap_yields_search_rows(seeded_conn,
                                                            capsys):
    payload = [
        {"clause_id": "9.2", "durable_document_id": "dur_0006-qm01",
         "heading": "Internal audit schedule", "chunk_id_if_known": None,
         "why": "audit program"},
        {"clause_id": "9.3", "durable_document_id": "dur_0006-qm01",
         "heading": "Management review minutes", "chunk_id_if_known": None,
         "why": "review cadence"},
    ]
    script = _no_match_roster_script(
        _json.dumps(_json.dumps(payload)),
        {"ops_charged": 1, "was_billable": True, "monthly_remaining": 480})
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient
    disc_client = SuperDocsClient(FixtureTransport(script))
    summary = discover.run_discover(disc_client, seeded_conn,
                                    _all_clauses())
    assert summary["ops_charged"] == 1
    assert len(summary["rows"]) == 2
    assert all(r["source"] == "search" for r in summary["rows"])
    rows = seeded_conn.execute(
        "SELECT * FROM shortlists ORDER BY clause_id").fetchall()
    assert [r["clause_id"] for r in rows] == ["9.2", "9.3"]
    assert rows[0]["heading_path"] == "Internal audit schedule"
    assert rows[0]["durable_document_id"] == "dur_0006-qm01"
    text = capsys.readouterr().out
    warned = ("WARN: discover could not shortlist 25 clauses" in text)
    assert warned


def test_fallback_fires_exactly_one_batched_turn_with_every_clause(
        seeded_conn, capsys):
    script = _no_match_roster_script(
        _json.dumps([]),
        {"ops_charged": 1, "was_billable": True, "monthly_remaining": 480})
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient
    disc_client = SuperDocsClient(FixtureTransport(script))
    discover.run_discover(disc_client, seeded_conn, _all_clauses())
    posts = [c for c in disc_client.t.calls if c == ("POST", "/v1/chat/async")]
    assert posts == [("POST", "/v1/chat/async")]
    body = next(b for b in disc_client.t.bodies if b and "Clauses:" in b.get(
        "message", ""))
    for clause in _all_clauses():
        if clause["linkable"]:
            assert clause["id"] in body["message"], clause["id"]
    assert "Search across ALL open documents" in body["message"]
    assert body.get("response_mode") == "compact"
    capsys.readouterr()


def test_ops_floor_propagates_as_stopped_exit_two(tmp_path, monkeypatch):
    root = str(tmp_path / "floor.db")
    conn = db.connect(root)
    seeded(conn)
    conn.close()
    monkeypatch.setenv("CK_FIXTURE",
                       str(FIXTURES_DIR / "discover_floor.json"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exc:
        cli.main(["--db", root, "link", "--discover"])
    assert exc.value.code == 2
    text = out.getvalue()
    assert "STOPPED:" in text
    assert "SHORTLIST" not in text
    conn = db.connect(root)
    assert conn.execute("SELECT COUNT(*) c FROM shortlists").fetchone()["c"] == 0
    conn.close()


def test_flag_off_call_sequence_and_writes_invariant(conn):
    client = client_for("init_link.json")
    ingest.init_session(client, conn, str(CORPUS))
    cli.sync_clauses(conn, _all_clauses())
    results = linking.build_links(client, conn, _all_clauses())
    assert len(results) == 6
    expected_calls = (
        [("POST", "/v1/sessions/init")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_p02/save")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_p03/save")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_p04/save")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_p05/save")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_p06/save")]
        + [("POST", "/v1/documents/upload"),
           ("POST", "/v1/sessions/ck-demo-01/documents/doc_qm01/save")]
        + [("GET", "/v1/sessions/ck-demo-01/documents"),
           ("GET", "/v1/sessions/ck-demo-01/documents"),
           ("GET", "/v1/sessions/ck-demo-01/documents")]
        + [(call, f"/v1/jobs/job_link_{i:02d}") if call == "GET"
           else (call, "/v1/chat/async")
           for i in range(1, 7) for call in
           ("POST", "GET")])
    assert client.t.calls == expected_calls
    assert len(client.usage_log) == 6
    assert conn.execute(
        "SELECT COUNT(*) c FROM shortlists").fetchone()["c"] == 0


def test_weak_results_warn_fallback_mapping_continues(tmp_path, monkeypatch):
    root = str(tmp_path / "weak.db")
    monkeypatch.setenv("CK_FIXTURE", str(FIXTURES_DIR / "init_link.json"))
    cli.main(["--db", root, "init", "--corpus", str(CORPUS)])
    monkeypatch.setenv("CK_FIXTURE",
                       str(FIXTURES_DIR / "discover_weak.json"))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["--db", root, "link", "--discover"])
    text = out.getvalue()
    assert "WARN: search returned usable candidates for only 0 of 15" in text
    assert ("WARN: discover could not shortlist 15 clauses - continuing"
            " with standard mapping (no candidates invented)") in text
    assert "linked NM-QM-01-quality-manual: 2 clauses covered" in text
    conn = db.connect(root)
    rows = conn.execute("SELECT source, COUNT(*) c FROM shortlists"
                        " GROUP BY source").fetchall()
    assert {r["source"]: r["c"] for r in rows} == {"local": 12}
    total = conn.execute("SELECT SUM(ops_charged) t FROM usage_log"
                         ).fetchone()["t"]
    assert total == 7
    conn.close()


def test_plan_preview_issues_zero_billable_calls(seeded_conn, capsys):
    script = _no_match_roster_script("unused", {})
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient
    plan_client = SuperDocsClient(FixtureTransport(script[:1]))
    projected = discover.plan_discover(plan_client, seeded_conn,
                                       _all_clauses())
    assert projected == 1
    assert not [c for c in plan_client.t.calls if c[0] == "POST"]
    assert plan_client.usage_log == []
    text = capsys.readouterr().out
    assert "DISCOVER PLAN (preview mode - zero billable ops)" in text
    assert "local match projects 0/27 resolvable from headings (0 ops)" in text
    assert "projected search spend: 1 op (one batched turn for" in text
    assert "estimated cost: <=1 op; spent so far: 0" in text


def test_cost_cap_over_one_op_fails_loudly(seeded_conn):
    script = _no_match_roster_script(
        _json.dumps([{"clause_id": "9.2"}]),
        {"ops_charged": 2, "was_billable": True, "monthly_remaining": 400})
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient
    greedy_client = SuperDocsClient(FixtureTransport(script))
    with pytest.raises(RuntimeError) as exc:
        discover.run_discover(greedy_client, seeded_conn, _all_clauses())
    assert "caps the batched pass at 1 op" in str(exc.value)
    assert seeded_conn.execute(
        "SELECT COUNT(*) c FROM shortlists").fetchone()["c"] == 0


def test_local_full_resolution_skips_search_turn(seeded_conn, capsys):
    titles = [c["title"] for c in _all_clauses() if c["linkable"]]
    html = "".join(
        f'<div data-chunk-id="cc{i}"><h2>{t}</h2><p>body</p></div>'
        for i, t in enumerate(titles))
    roster = {"documents": [
        {"document_id": slot, "html": html}
        for slot in ("doc_p02", "doc_p03", "doc_p04", "doc_p05", "doc_p06",
                     "doc_qm01")]}
    script = [{"method": "GET", "path": "/v1/sessions/ck-demo-01/documents",
               "params": {"include_html": "true"}, "responses": [roster]}]
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient
    quiet_client = SuperDocsClient(FixtureTransport(script))
    summary = discover.run_discover(quiet_client, seeded_conn,
                                    _all_clauses())
    assert summary["ops_charged"] == 0
    assert not [c for c in quiet_client.t.calls if c[0] == "POST"]
    assert all(r["source"] == "local" for r in summary["rows"])
    covered = {r["clause_id"] for r in seeded_conn.execute(
        "SELECT clause_id FROM shortlists WHERE source = 'local'"
        ).fetchall()}
    assert covered == {c["id"] for c in _all_clauses() if c["linkable"]}
    text = capsys.readouterr().out
    assert ("search turn skipped - local shortlist covered every clause"
            " (0 ops)") in text


def test_number_prefix_heading_matches_clause_number():
    html = ('<div data-chunk-id="n85"><h2>8.5 Manufacturing and delivery</h2>'
            '<p>x</p></div>')
    chunks = ingest.extract_chunks(html)
    hit = discover._number_prefix_hit(chunks, "8.5")
    assert hit is not None and hit["chunk_id"] == "n85"
    assert discover._number_prefix_hit(chunks, "8.5.1") is None
