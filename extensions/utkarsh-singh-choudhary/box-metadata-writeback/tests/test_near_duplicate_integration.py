from app.clients.fake_box_client import FakeBoxClient
from app.clients.fake_superdocs_client import FakeSuperDocsClient
from app.workflow.pipeline import BoxMetadataWritebackPipeline

CONTRACT_A = b"""SERVICES AGREEMENT
Counterparty: Acme Logistics Inc
Effective Date: 2026-01-15
Expiration Date: 2027-01-14
Value: $84,000
This agreement covers logistics management services provided on an ongoing basis
throughout the term with quarterly review checkpoints and standard termination clauses.
"""

CONTRACT_A_TRIVIAL_EDIT = CONTRACT_A.replace(b"2026-01-15", b"2026-01-16")

CONTRACT_B_UNRELATED = b"""INVOICE
Amount Due: $500
Bill To: Totally Different Company
This is a completely unrelated one-time invoice for consulting services rendered
in a single engagement with no relation whatsoever to any other document.
"""


def make_pipeline():
    box = FakeBoxClient()
    sd = FakeSuperDocsClient()
    return box, BoxMetadataWritebackPipeline(box, sd, retry_sleep_fn=lambda s: None)


def test_first_processed_file_has_no_near_duplicate_flag():
    box, pipeline = make_pipeline()
    box.seed_file("f1", "c1.txt", CONTRACT_A)
    report = pipeline.process("f1")
    assert report.near_duplicate_of is None


def test_near_duplicate_under_a_different_file_id_is_flagged():
    box, pipeline = make_pipeline()
    box.seed_file("f1", "c1.txt", CONTRACT_A)
    pipeline.process("f1")

    box.seed_file("f2", "c2.txt", CONTRACT_A_TRIVIAL_EDIT)
    report = pipeline.process("f2")
    assert report.near_duplicate_of == "f1"
    assert report.near_duplicate_similarity > 0.5


def test_near_duplicate_does_not_block_processing():
    """Flagging is informational only -- metadata still gets written
    normally for the flagged file, it just carries extra information
    about a likely duplicate."""
    box, pipeline = make_pipeline()
    box.seed_file("f1", "c1.txt", CONTRACT_A)
    pipeline.process("f1")

    box.seed_file("f2", "c2.txt", CONTRACT_A_TRIVIAL_EDIT)
    report = pipeline.process("f2")
    assert report.near_duplicate_of == "f1"
    assert report.metadata_written.get("counterparty_name") == "Acme Logistics Inc"


def test_unrelated_documents_are_not_flagged_against_each_other():
    box, pipeline = make_pipeline()
    box.seed_file("f1", "c1.txt", CONTRACT_A)
    pipeline.process("f1")

    box.seed_file("f2", "c2.txt", CONTRACT_B_UNRELATED)
    report = pipeline.process("f2")
    assert report.near_duplicate_of is None


def test_reprocessing_a_version_bump_of_the_same_file_id_is_not_self_flagged():
    box, pipeline = make_pipeline()
    box.seed_file("f1", "c1.txt", CONTRACT_A)
    pipeline.process("f1")
    box.bump_version("f1", CONTRACT_A_TRIVIAL_EDIT, "2")
    report = pipeline.process("f1")
    assert report.near_duplicate_of is None


def test_near_duplicate_over_http():
    from fastapi.testclient import TestClient

    import app.api.main as m
    from app.api.main import app

    client = TestClient(app)
    ctx = m._tenants.context_for("default")
    ctx.box.seed_file("dup-http-1", "c1.txt", CONTRACT_A)
    client.post("/process/dup-http-1")

    ctx.box.seed_file("dup-http-2", "c2.txt", CONTRACT_A_TRIVIAL_EDIT)
    resp = client.post("/process/dup-http-2")
    assert resp.status_code == 200
    body = resp.json()
    assert body["near_duplicate_of"] == "dup-http-1"
    assert body["near_duplicate_similarity"] > 0.5
