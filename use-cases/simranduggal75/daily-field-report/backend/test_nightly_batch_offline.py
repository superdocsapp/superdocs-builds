"""
Offline pytest tests for app.services.nightly_batch. No network calls,
no SUPERDOCS_API_KEY required - process_report is monkeypatched so
nothing here touches the live SuperDocs API.

Uses asyncio.run() inside plain test functions rather than pulling in
the pytest-asyncio plugin, to keep the dependency footprint minimal.
"""

import asyncio
import json

import app.services.nightly_batch as nightly_batch
from app.services import report_store
from app.services.report_pipeline import ReportPipelineError


def _make_report(reports_dir, name, status, has_notes=True, photos=None, project=None):
    report_dir = reports_dir / name
    report_dir.mkdir()
    if has_notes:
        (report_dir / "notes.txt").write_text("Some field notes.", encoding="utf-8")
    metadata = {
        "report_id": name,
        "has_notes": has_notes,
        "photo_count": len(photos or []),
        "photos": photos or [],
        "status": status,
        "project": project,
        "report_date": None,
        "project_mismatch": None,
        "failure_reason": None,
    }
    (report_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return report_dir


def test_batch_isolates_failures_skips_empty_and_is_idempotent(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    report_a = _make_report(reports_dir, "report-a", "pending")
    report_b = _make_report(reports_dir, "report-b", "received")  # legacy status
    report_c = _make_report(reports_dir, "report-c", "awaiting_approval")  # already processed
    report_d = _make_report(reports_dir, "report-d", "pending", has_notes=False, photos=[])

    async def fake_process_report(*, report_id, report_dir, notes, photo_filenames, explicit_project=None):
        if report_id == "report-a":
            report_store.update_metadata(report_dir, status="awaiting_approval")
            return {"status": "awaiting_approval"}
        if report_id == "report-b":
            report_store.update_metadata(report_dir, status="failed", failure_reason="Simulated failure")
            raise ReportPipelineError("Simulated failure")
        raise AssertionError(f"process_report should not be called for {report_id}")

    monkeypatch.setattr(nightly_batch, "process_report", fake_process_report)

    summary_1 = asyncio.run(nightly_batch.run_nightly_batch(storage_dir=reports_dir))

    # report-c is already past pending-like status and must never be a candidate
    assert summary_1["candidates_found"] == 3
    assert summary_1["processed_count"] == 1
    assert summary_1["failed_count"] == 1
    assert summary_1["skipped_count"] == 1
    assert summary_1["processed"][0]["report_id"] == "report-a"
    assert summary_1["failed"][0]["report_id"] == "report-b"
    assert summary_1["skipped"][0]["report_id"] == "report-d"

    assert report_store.read_metadata(report_a)["status"] == "awaiting_approval"
    assert report_store.read_metadata(report_b)["status"] == "failed"
    assert report_store.read_metadata(report_c)["status"] == "awaiting_approval"  # untouched
    assert report_store.read_metadata(report_d)["status"] == "pending"  # skip doesn't change status

    # Idempotency: running again must not reprocess report-a or report-b,
    # since process_report would raise AssertionError if called for them.
    summary_2 = asyncio.run(nightly_batch.run_nightly_batch(storage_dir=reports_dir))

    assert summary_2["candidates_found"] == 1  # only report-d remains pending-like
    assert summary_2["processed_count"] == 0
    assert summary_2["failed_count"] == 0
    assert summary_2["skipped_count"] == 1


def test_batch_writes_one_summary_file_per_day(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    batches_dir = tmp_path / "batches"

    _make_report(reports_dir, "report-x", "pending", has_notes=False, photos=[])

    asyncio.run(nightly_batch.run_nightly_batch(storage_dir=reports_dir, batches_dir=batches_dir))
    asyncio.run(nightly_batch.run_nightly_batch(storage_dir=reports_dir, batches_dir=batches_dir))

    summary_files = list(batches_dir.glob("*.json"))
    assert len(summary_files) == 1


def test_batch_with_no_pending_reports_returns_empty_summary(tmp_path):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()

    summary = asyncio.run(nightly_batch.run_nightly_batch(storage_dir=reports_dir))

    assert summary["candidates_found"] == 0
    assert summary["processed_count"] == 0
    assert summary["failed_count"] == 0
    assert summary["skipped_count"] == 0
