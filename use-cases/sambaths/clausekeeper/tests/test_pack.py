import json
from pathlib import Path

import pytest

from conftest import FIXTURES, PROJECT, client_for, seeded_conn  # noqa: F401

from clausekeeper import guards, packing
from clausekeeper.library import LIBRARY_PATH
from clausekeeper.superdocs import FixtureTransport

TEMPLATE = str(PROJECT / "assets" / "northgate-letterhead.docx")


def _run_pack(client, conn, tmp_path, **kw):
    out = tmp_path / "exports"
    return packing.build_pack(
        client, conn, template_path=kw.pop("template_path", TEMPLATE),
        out_dir=str(out), library_path=str(LIBRARY_PATH), **kw)


def test_pack_generates_exports_and_guards(seeded_conn, tmp_path):
    client = client_for("pack_flow.json")
    summary = _run_pack(client, seeded_conn, tmp_path)

    assert summary["template"] == {"template_id": "tpl_lh_01",
                                   "reused": False}
    assert summary["document"]["session_slot_id"] == "doc_pack_01"
    row = seeded_conn.execute(
        "SELECT role, durable_document_id FROM documents WHERE"
        " session_slot_id = 'doc_pack_01'").fetchone()
    assert row["role"] == "generated"
    assert row["durable_document_id"] == "dur_pack_01"
    assert guards.role_allows(dict(row)) is False

    docx, pdf = summary["exports"]
    assert Path(docx["path"]).exists() and Path(pdf["path"]).exists()
    assert docx["warnings"] == ["font Calibri substituted on page 2"]
    assert pdf["warnings"] == []
    assert summary["ops_spent"] == 1
    assert summary["language_rail"] == "clean"

    assert seeded_conn.execute(
        "SELECT 1 FROM our_jobs WHERE job_id = 'job_pack_01'"
    ).fetchone()
    assert seeded_conn.execute(
        "SELECT kind FROM runs WHERE run_key = 'pack:job_pack_01'"
    ).fetchone()["kind"] == "pack"


def test_template_uploaded_once_then_reused(seeded_conn, tmp_path):
    client = client_for("pack_flow.json")
    _run_pack(client, seeded_conn, tmp_path)
    client.t = FixtureTransport(FIXTURES / "pack_flow_reuse_cycle.json")
    summary = packing.build_pack(client, seeded_conn,
                                 out_dir=str(tmp_path / "e2"),
                                 library_path=str(LIBRARY_PATH))
    assert summary["template"] == {"template_id": "tpl_lh_01",
                                   "reused": True}
    uploads = [c for c in client.t.calls
               if c == ("POST", "/v1/templates/upload")]
    assert len(uploads) == 0
    assert summary["document"]["session_slot_id"] == "doc_pack_02"


def test_missing_template_refuses_without_stored_id(seeded_conn):
    with pytest.raises(RuntimeError, match="--template"):
        packing.build_pack(client_for("pack_flow.json"), seeded_conn,
                           template_path=None)


def test_language_rail_blocks_claim_tokens():
    matrix = {"rows": [], "covered": 0, "total": 26, "pct": 0,
              "uncovered": [], "gaps": [{"clause_id": "8.7",
                                         "narrative": "now certified"}],
              "stale": 0}
    with pytest.raises(packing.LanguageRailError):
        packing.render_prompt(matrix, "lh.docx")

    prompt = packing.render_prompt({"rows": [], "covered": 3, "total": 4,
                                    "pct": 75, "uncovered": [], "gaps": [],
                                    "stale": 0}, "lh.docx")
    assert packing.READINESS_PHRASE in prompt
    packing.assert_language_rail(prompt)
    assert not packing.FORBIDDEN_RE.search(packing.HONEST_LIMITS)

    with pytest.raises(packing.LanguageRailError):
        packing.assert_language_rail("<p>fully certified by ISO</p>")


def test_collect_matrix_counts(seeded_conn):
    seeded_conn.execute(
        "INSERT INTO documents(session_slot_id, durable_document_id, role,"
        " name) VALUES('x', 'dx', 'manual', 'M')")
    seeded_conn.commit()
    matrix = packing.collect_matrix(seeded_conn, str(LIBRARY_PATH))
    assert matrix["total"] > 0
    assert matrix["covered"] >= 1
    assert 0 <= matrix["pct"] <= 100
