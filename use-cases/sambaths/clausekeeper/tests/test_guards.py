import pytest

from conftest import client_for, seeded_conn

from clausekeeper import guards, rechecking


def test_rename_keeps_links_and_refreshes_display_name(seeded_conn):
    before = seeded_conn.execute(
        "SELECT clause_id, chunk_id, status FROM links ORDER BY link_id"
        ).fetchall()
    detection = rechecking.detect_changed(
        client_for("events_recheck.json"), seeded_conn)
    assert detection["renamed"] == 1
    name = seeded_conn.execute(
        "SELECT name FROM documents WHERE session_slot_id = 'doc_p02'"
        ).fetchone()["name"]
    assert name == "NM-PRO-02-controlled-documents"
    after = seeded_conn.execute(
        "SELECT clause_id, chunk_id, status FROM links ORDER BY link_id"
        ).fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_echo_suppression_ignores_own_jobs(seeded_conn):
    detection = rechecking.detect_changed(
        client_for("events_recheck.json"), seeded_conn)
    names = {d["session_slot_id"] for d in detection["changed"]}
    assert names == {"doc_p04"}
    assert detection["skipped_echo"] == 1


def test_generated_docs_never_enqueue_rechecks(seeded_conn):
    seeded_conn.execute(
        "INSERT OR REPLACE INTO documents(session_slot_id, role, name,"
        " version_hash) VALUES('doc_gen_pack', 'generated', 'audit-pack', '')")
    conn = seeded_conn
    doc = {"role": "generated"}
    assert not guards.role_allows(doc)
    assert guards.role_allows({"role": "manual"})
    detection = rechecking.detect_changed(client_for("events_recheck.json"),
                                          conn)
    names = {d["session_slot_id"] for d in detection["changed"]}
    assert "doc_gen_pack" not in names


def test_same_version_hash_rerun_skips(seeded_conn):
    first_client = client_for("events_recheck.json")
    summary = rechecking.run_recheck(first_client, seeded_conn)
    assert summary["results"], "first pass should verify one document"
    ops_first = sum(u["ops_charged"] for u in first_client.usage_log)
    assert ops_first == 1

    second_client = client_for("events_recheck.json")
    second = rechecking.run_recheck(second_client, seeded_conn)
    assert second["already_checked"]
    assert second_client.usage_log == []
    assert second["ops_spent"] == 0
