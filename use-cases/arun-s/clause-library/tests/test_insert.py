"""Keyless proof of the insert/export hand-off, with a fake SuperDocs."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from superdocs_min import SuperDocs, insert_clause


def _fake(method, url, headers, body):
    if url.endswith("/chat/async"):
        assert "Insert this clause" in body["message"]        # the instruction carries the clause
        return 200, '{"job_id":"j1","status":"completed"}'
    if url.endswith("/documents/export"):
        return 200, "PK\x03\x04 fake-docx"
    return 404, ""


def test_insert_clause_sends_and_exports():
    sd = SuperDocs("k", transport=_fake)
    docx = insert_clause(sd, "<p>1. Services...</p>", "Either party may terminate on thirty days notice.",
                         section_hint="Termination")
    assert len(docx) > 0
