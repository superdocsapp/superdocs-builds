"""Idempotency: an operation that costs money must not be bought twice for
identical work — and must never claim 'already done' about a file that is gone."""
from __future__ import annotations

from supplier_quality_drafter.ledger import RunLedger, fingerprint


def _template(tmp_path, content=b"<h1>Customer Template</h1>"):
    p = tmp_path / "template.html"
    p.write_bytes(content)
    return str(p)


def test_same_inputs_produce_the_same_fingerprint(tmp_path):
    t = _template(tmp_path)
    a = fingerprint("s1", "draft this", t, "docx")
    b = fingerprint("s1", "draft this", t, "docx")
    assert a == b


def test_changing_the_instruction_changes_the_fingerprint(tmp_path):
    t = _template(tmp_path)
    assert fingerprint("s1", "draft this", t, "docx") != fingerprint("s1", "draft THAT", t, "docx")


def test_editing_the_template_in_place_changes_the_fingerprint(tmp_path):
    """Hashed by content, not by path — same filename, new bytes, new draft."""
    t = _template(tmp_path, b"<h1>Version 1</h1>")
    before = fingerprint("s1", "draft", t, "docx")
    (tmp_path / "template.html").write_bytes(b"<h1>Version 2</h1>")
    assert fingerprint("s1", "draft", t, "docx") != before


def test_changing_export_format_changes_the_fingerprint(tmp_path):
    t = _template(tmp_path)
    assert fingerprint("s1", "draft", t, "docx") != fingerprint("s1", "draft", t, "pdf")


def test_recorded_run_is_found_again(tmp_path):
    out = tmp_path / "out.docx"
    out.write_bytes(b"result")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    ledger.record("fp1", session_id="s1", export_path=str(out), job_id="job-1")
    found = ledger.lookup("fp1")
    assert found is not None
    assert found.job_id == "job-1"


def test_recorded_run_whose_output_was_deleted_is_not_treated_as_done(tmp_path):
    """The file on disk is the source of truth. Reporting 'already done' while
    pointing at a missing file would be a success message that isn't true."""
    out = tmp_path / "out.docx"
    out.write_bytes(b"result")
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    ledger.record("fp1", session_id="s1", export_path=str(out), job_id="job-1")
    out.unlink()
    assert ledger.lookup("fp1") is None


def test_unknown_fingerprint_is_not_found(tmp_path):
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    assert ledger.lookup("never-seen") is None


def test_corrupt_ledger_does_not_block_drafting(tmp_path):
    """Worst case of ignoring a corrupt ledger is one redundant operation.
    Worst case of honoring it is refusing to work at all — so it degrades open."""
    path = tmp_path / "ledger.json"
    path.write_text("{not valid json", encoding="utf-8")
    ledger = RunLedger(str(path))
    assert ledger.lookup("fp1") is None
    out = tmp_path / "out.docx"
    out.write_bytes(b"x")
    ledger.record("fp1", session_id="s1", export_path=str(out), job_id="job-1")
    assert ledger.lookup("fp1") is not None


def test_ledger_survives_multiple_records(tmp_path):
    ledger = RunLedger(str(tmp_path / "ledger.json"))
    for i in range(3):
        out = tmp_path / f"out{i}.docx"
        out.write_bytes(b"x")
        ledger.record(f"fp{i}", session_id=f"s{i}", export_path=str(out), job_id=f"job-{i}")
    assert all(ledger.lookup(f"fp{i}") is not None for i in range(3))
