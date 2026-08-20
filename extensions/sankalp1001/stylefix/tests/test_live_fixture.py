"""Tests driven by payloads captured from the live API on 2026-08-19.

Everything else in this suite runs against HTML and envelopes I wrote. These run
against what SuperDocs actually returned, which is the only reason to believe the
field names are right. The fixtures are committed alongside.

Capturing them changed the design: the live `pending_changes` carries `old_html` and
`new_html` for a whole chunk, not the `original`/`replacement` text span the earlier
code expected. Against the real payload that code produced empty targets, and the
guard refused every change — the linter would have applied nothing, silently.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stylefix.guard import screen  # noqa: E402
from stylefix.lint import _chunks_from_attributes  # noqa: E402
from stylefix.parsing import parse_proposed_changes  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_live_job_envelope_parses():
    """metadata.pending_changes, from a real awaiting_approval job."""
    changes = parse_proposed_changes(_load("get_job_awaiting_approval.json"))
    assert len(changes) == 3
    assert all(c.chunk_id and c.old_html and c.new_html for c in changes)


def test_text_edit_is_recovered_from_chunk_html():
    """The API proposes whole-chunk HTML; the guard needs the words that changed."""
    changes = parse_proposed_changes(_load("get_job_awaiting_approval.json"))
    by_id = {c.change_id[:8]: c for c in changes}
    assert by_id["cc3f6a9a"].original == "The Webhook"
    assert by_id["cc3f6a9a"].replacement == "the webhook"
    assert by_id["ea2646be"].original == "terminate"
    assert by_id["ea2646be"].replacement == "end"


def test_chunk_ids_are_read_from_data_chunk_id_attributes():
    """Chunk ids arrive as attributes on elements, not as a separate list."""
    doc = _load("upload_document.json")
    chunks = _chunks_from_attributes(doc["html"])
    assert len(chunks) == 5
    assert chunks["8edb9574-705d-4a1c-b6e0-bd4101efe720"].startswith("<pre")


def test_guard_clears_the_real_prose_edits_and_nothing_else():
    """The whole pipeline against real payloads: every proposed change screened
    against the document SuperDocs actually produced."""
    doc = _load("upload_document.json")["html"]
    changes = parse_proposed_changes(_load("get_job_awaiting_approval.json"))
    verdicts = {c.change_id[:8]: screen(doc, c.original, frozenset(), c.old_html)
                for c in changes}
    assert all(v.kept for v in verdicts.values()), \
        {k: v.reason for k, v in verdicts.items() if not v.kept}


def test_a_code_sample_edit_would_be_refused_against_the_real_document():
    """The proposal the model did not make, but which the guard must refuse if it
    ever does: the <pre> chunk from the real upload."""
    doc = _load("upload_document.json")["html"]
    pre_chunk = _chunks_from_attributes(doc)["8edb9574-705d-4a1c-b6e0-bd4101efe720"]
    v = screen(doc, "client.utilize(please=True)", frozenset(), pre_chunk)
    assert not v.kept and v.reason == "protected: inside <code>"


def test_attachment_readiness_shape():
    """Readiness is total_ready with total_processing at zero — not a status scalar."""
    status = _load("attachment_status.json")
    assert status["total_ready"] == 1 and status["total_processing"] == 0
    assert status["processing_jobs"][0]["status"] == "completed"
