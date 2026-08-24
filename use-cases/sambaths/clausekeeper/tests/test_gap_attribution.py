import pytest

from conftest import client_for, seeded_conn

from clausekeeper import editing


def always_approve(change):
    return True


def test_multi_chunk_section_delete_orphans_every_deleted_chunk(seeded_conn):
    from clausekeeper import db as ckdb
    conn = seeded_conn
    dur = "dur_0003-p04"
    for cid in ("h-chunk", "p-chunk"):
        conn.execute(
            "INSERT INTO links(clause_id, durable_document_id, chunk_id,"
            " heading_path, quote_excerpt, status)"
            " VALUES('8.7', ?, ?, 'Disposition', 'quote', 'covered')",
            (dur, cid))
    conn.commit()
    cur = conn.execute(
        "INSERT INTO edits(job_id, change_id, durable_document_id, chunk_id,"
        " operation, occurred_at, causing_instruction)"
        " VALUES('job_x', 'chg_99', ?, 'h-chunk', 'delete',"
        " '2026-08-23T00:00:00Z', 'remove disposition')",
        (dur,))
    conn.commit()
    doc = conn.execute(
        "SELECT * FROM documents WHERE session_slot_id = 'doc_p04'"
        ).fetchone()
    diff = {"change_id": "chg_99", "operation": "delete",
            "chunk_id": "unrelated-new-id",
            "old_html": '<h2 data-chunk-id="h-chunk">3 Disposition of'
                        ' nonconforming devices</h2><p data-chunk-id='
                        '"p-chunk">Dispositions are decided by the QA'
                        ' Manager.</p>',
            "new_html": ""}
    landed = editing._land_gaps(conn, doc, diff, cur.lastrowid, "remove disposition",
                                "job_x", "2026-08-23T00:00:00Z", ckdb.now())
    assert landed == 1
    statuses = {r["chunk_id"]: r["status"] for r in conn.execute(
        "SELECT chunk_id, status FROM links WHERE durable_document_id = ?"
        " AND chunk_id IN ('h-chunk','p-chunk')", (dur,))}
    assert statuses == {"h-chunk": "gap", "p-chunk": "gap"}
    narratives = conn.execute(
        "SELECT COUNT(*) c FROM gaps g JOIN edits e ON e.edit_id ="
        " g.cause_edit_id WHERE g.clause_id = '8.7' AND e.change_id ="
        " 'chg_99'").fetchone()["c"]
    assert narratives == 1


def test_gap_lands_synchronously_naming_the_cause(seeded_conn):
    transport = client_for("edit_delete.json")
    summary = editing.guided_edit(
        transport, seeded_conn, "NM-PRO-04",
        "Delete the entire 'Disposition of nonconforming devices' section;"
        " disposition decisions now live only in the ERP workflow.",
        decide=always_approve)

    assert summary["gaps_landed"] == 1
    gap = seeded_conn.execute(
        "SELECT g.narrative, g.detected_at, e.change_id, e.job_id,"
        " e.causing_instruction FROM gaps g JOIN edits e ON"
        " e.edit_id = g.cause_edit_id WHERE g.clause_id = '8.7'"
        ).fetchone()
    assert gap is not None
    assert gap["change_id"] == "chg_42"
    assert gap["job_id"] == "job_edit_01"
    assert "Disposition of nonconforming devices" in gap["narrative"]
    assert "chg_42" in gap["narrative"]
    assert "job_edit_01" in gap["narrative"]
    assert "14:02:00Z" in gap["narrative"]
    assert "ERP workflow" in gap["narrative"]

    link = seeded_conn.execute(
        "SELECT status FROM links WHERE clause_id = '8.7'").fetchone()
    assert link["status"] == "gap"

    billable_after = [c for c in transport.t.calls if c == ("POST", "/v1/chat")]
    assert billable_after == []


def test_own_job_registered_for_echo_suppression(seeded_conn):
    editing.guided_edit(client_for("edit_delete.json"), seeded_conn,
                        "NM-PRO-04", "remove disposition", decide=lambda c: True)
    row = seeded_conn.execute(
        "SELECT 1 FROM our_jobs WHERE job_id = 'job_edit_01'").fetchone()
    assert row is not None


def test_denied_change_sends_explicit_rejection(seeded_conn):
    client = client_for("edit_delete.json")
    editing.guided_edit(client, seeded_conn, "NM-PRO-04",
                        "Delete the disposition section.",
                        decide=lambda c: (False, "keep the section"))
    approve_idx = [i for i, c in enumerate(client.t.calls)
                   if c[1] == "/v1/chat/ck-demo-01/approve"]
    assert len(approve_idx) == 1
    body = client.t.bodies[approve_idx[0]]
    assert body["approved"] is False
    assert body["changes"][0]["change_id"] == "chg_42"
    assert body["changes"][0]["approved"] is False
    assert body["changes"][0]["feedback"] == "keep the section"
