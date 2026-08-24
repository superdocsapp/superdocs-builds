from conftest import CORPUS, client_for, seeded

from clausekeeper import ingest, linking


def test_init_binds_durable_ids_and_roles(conn):
    client = client_for("init_link.json")
    result = ingest.init_session(client, conn, str(CORPUS))
    assert result["documents"] == 6
    assert result["unbound"] == 0
    rows = conn.execute(
        "SELECT session_slot_id, durable_document_id, role, name"
        " FROM documents").fetchall()
    assert all(r["durable_document_id"] for r in rows)
    roles = {r["session_slot_id"]: r["role"] for r in rows}
    assert roles["doc_qm01"] == "manual"
    assert roles["doc_p04"] == "procedure"
    assert conn.execute("SELECT COUNT(*) c FROM documents WHERE role = 'manual'"
                        ).fetchone()["c"] == 1


def test_link_records_provenance(seeded_conn):
    row = seeded_conn.execute(
        "SELECT l.*, d.name AS doc FROM links l JOIN documents d ON"
        " d.durable_document_id = l.durable_document_id WHERE l.clause_id='8.7'"
        ).fetchone()
    assert row is not None
    assert row["chunk_id"] == "c_ncr_disp"
    assert row["status"] == "covered"
    assert "Disposition" in row["heading_path"]
    assert "QA Manager" in row["quote_excerpt"]
    assert row["last_verified_at"]


def test_seed_holes_detected_by_audit(seeded_conn):
    audit = linking.audit_against_expected(seeded_conn, str(CORPUS /
                                         "expected-gaps.yaml"))
    by_seed = {a["seed"]: a for a in audit}
    assert by_seed["SEED-H1"]["clause_id"] == "9.2"
    assert by_seed["SEED-H1"]["detected"] is True
    assert by_seed["SEED-H2"]["clause_id"] == "7.4"
    assert by_seed["SEED-H2"]["detected"] is True


def test_unparseable_mapping_skips_doc_without_killing_pass(seeded_conn):
    from conftest import client_for as base_client_for
    from clausekeeper.library import LIBRARY_PATH, load_library
    from clausekeeper.superdocs import FixtureTransport, SuperDocsClient

    starts = [{"job_id": f"job_garbage_{i}", "status": "pending"}
              for i in range(6)]
    polls = []
    for i in range(6):
        polls.append({"job_id": f"job_garbage_{i}", "status": "completed",
                      "result": {"response":
                                 "I reviewed the document and it looks well "
                                 "aligned with the standard.",
                                 "usage": {"ops_charged": 1,
                                           "was_billable": True,
                                           "monthly_remaining": 480}}})
    roster = {"documents": [
        {"document_id": f"doc_p0{n}", "html":
         '<h1>t</h1><div data-chunk-id="cx"><h2>s</h2><p>body</p></div>'}
        for n in (2, 3, 4, 5, 6)] + [
        {"document_id": "doc_qm01", "html":
         '<h1>t</h1><div data-chunk-id="cx9"><h2>s</h2><p>body</p></div>'}]}
    script = [
        {"method": "GET", "path": "/v1/sessions/ck-demo-01/documents",
         "params": {"include_html": "true"}, "responses": [roster]},
        {"method": "POST", "path": "/v1/chat/async", "responses": starts},
        {"method": "GET", "path": "/v1/jobs/{id}", "responses": polls},
    ]
    client = SuperDocsClient(FixtureTransport(script))
    results = linking.build_links(client, seeded_conn,
                                  load_library(LIBRARY_PATH))
    assert len(results) == 6
    assert all(r["parse_failed"] for r in results)
    before = seeded_conn.execute("SELECT COUNT(*) n FROM links").fetchone()["n"]
    assert before > 0


def test_link_costs_one_op_per_document(conn):
    client = client_for("init_link.json")
    ingest.init_session(client, conn, str(CORPUS))
    from clausekeeper.library import LIBRARY_PATH, load_library
    linking.build_links(client, conn, load_library(LIBRARY_PATH))
    link_calls = [c for c in client.t.calls if c == ("POST", "/v1/chat/async")]
    assert len(link_calls) == 6
    assert len(client.usage_log) == 6
    assert all(u["ops_charged"] == 1 for u in client.usage_log)
    sync_chats = [c for c in client.t.calls if c == ("POST", "/v1/chat")]
    assert sync_chats == []
    document_gets = [c for c in client.t.calls
                     if c[0] == "GET" and c[1].startswith("/v1/documents/")]
    assert document_gets == []
