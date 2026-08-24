from __future__ import annotations

from pathlib import Path

from drift_check.superdocs import LocalSuperDocsAdapter, credential_status


def test_live_status_never_claims_verified_without_a_real_call() -> None:
    assert credential_status() == "PENDING_NOT_CONFIGURED"


def test_local_adapter_upload_and_export_roundtrip(tmp_path: Path) -> None:
    adapter = LocalSuperDocsAdapter(tmp_path / "work")
    adapter.upload(document_ref="doc1", content="hello world")
    result = adapter.export(document_ref="doc1", destination_dir=str(tmp_path / "out"))
    assert Path(result.exported_path).read_text(encoding="utf-8") == "hello world"
    assert adapter.live_status() == "PENDING_NOT_CONFIGURED"


def test_propose_edit_is_recorded_not_applied(tmp_path: Path) -> None:
    adapter = LocalSuperDocsAdapter(tmp_path / "work")
    adapter.upload(document_ref="doc1", content="original translation text")
    adapter.propose_edit(document_ref="doc1", section_ref="S1", corrected_text="fixed text", rationale="drift found")
    assert len(adapter.proposed_edits) == 1
    # Proposing an edit must not mutate the uploaded content until a human
    # decision is recorded and something explicitly applies it.
    result = adapter.export(document_ref="doc1", destination_dir=str(tmp_path / "out"))
    assert Path(result.exported_path).read_text(encoding="utf-8") == "original translation text"


def test_review_decisions_are_recorded(tmp_path: Path) -> None:
    adapter = LocalSuperDocsAdapter(tmp_path / "work")
    adapter.record_review_decision(document_ref="doc1", section_ref="S1", decision="approved")
    assert adapter.review_decisions == [{"document_ref": "doc1", "section_ref": "S1", "decision": "approved"}]
