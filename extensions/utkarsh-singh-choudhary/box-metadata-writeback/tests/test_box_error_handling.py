from fastapi.testclient import TestClient

import app.api.main as m
from app.api.main import app

CONTRACT = b"SERVICES AGREEMENT\nCounterparty: Acme Logistics Inc\nEffective Date: 2026-01-15\nValue: $84,000\n"


def fresh_client():
    return TestClient(app)


def test_process_unknown_file_id_returns_404_not_500():
    client = fresh_client()
    resp = client.post("/process/this-file-id-was-never-seeded")
    assert resp.status_code == 404
    assert "not accessible" in resp.json()["detail"].lower()


def test_batch_with_one_bad_file_id_does_not_crash_the_whole_batch():
    client = fresh_client()
    good_ids = [f"batch-good-{i}" for i in range(5)]
    for fid in good_ids:
        m._tenants.context_for("default").box.seed_file(fid, f"{fid}.pdf", CONTRACT)
    bad_id = "batch-bad-unseeded-file"

    resp = client.post("/process/batch", json={"file_ids": good_ids + [bad_id]})
    assert resp.status_code == 200
    body = resp.json()

    assert body["processed"] == 5
    assert body["failed"] == 1
    assert body["results"][bad_id]["status"] == "failed"
    assert "not accessible" in body["results"][bad_id]["error"].lower()
    for fid in good_ids:
        assert body["results"][fid]["status"] == "processed"


def test_batch_failed_entries_dont_break_total_operations_summation():
    client = fresh_client()
    m._tenants.context_for("default").box.seed_file("batch-ok-1", "ok.pdf", CONTRACT)
    resp = client.post("/process/batch", json={"file_ids": ["batch-ok-1", "batch-missing-1"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_operations"] > 0  # counted from the successful run only, no KeyError
