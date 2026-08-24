from conftest import CORPUS, client_for, seeded_conn

from clausekeeper import ingest, linking, rechecking
from clausekeeper.library import LIBRARY_PATH, load_library


def test_plan_spends_zero_billable_ops(seeded_conn):
    client = client_for("events_recheck.json")
    detection = rechecking.detect_changed(client, seeded_conn)
    plan = rechecking.build_plan(client, seeded_conn, detection)

    assert plan["estimated_ops"] == 1
    item = plan["items"][0]
    assert item["name"] == "NM-PRO-04-nonconforming-output"
    assert set(item["clauses"]) == {"8.7", "10.2"}

    billable = [c for c in client.t.calls if c[0] == "POST"]
    assert billable == []
    assert client.usage_log == []


def test_run_updates_matrix_and_reports_ops(seeded_conn):
    client = client_for("events_recheck.json")
    summary = rechecking.run_recheck(client, seeded_conn)

    assert summary["ops_spent"] == 1
    statuses = dict(seeded_conn.execute(
        "SELECT clause_id, status FROM links WHERE durable_document_id ="
        " 'dur_0003-p04'").fetchall())
    assert statuses["8.7"] == "gap"
    assert statuses["10.2"] == "covered"

    link = seeded_conn.execute(
        "SELECT last_verified_job, heading_path FROM links WHERE clause_id ="
        " '10.2'").fetchone()
    assert link["heading_path"] == "Corrective action"

    run_rows = seeded_conn.execute("SELECT * FROM runs").fetchall()
    assert len(run_rows) == 1
    assert run_rows[0]["status"] == "done"


def test_verification_gap_creates_row_with_narrative(seeded_conn):
    verify_client = client_for("events_recheck.json")
    rechecking.run_recheck(verify_client, seeded_conn)
    gap = seeded_conn.execute(
        "SELECT narrative FROM gaps WHERE clause_id = '8.7'").fetchone()
    assert gap is not None
    assert "no covering section" in gap["narrative"]
