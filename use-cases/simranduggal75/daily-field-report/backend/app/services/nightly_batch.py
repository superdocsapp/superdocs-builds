"""
Nightly batch: catch-up processing for reports left in a pending state.

POST /api/v1/reports already processes reports synchronously (see
PROGRESS.md for why), so under normal operation this batch has nothing
to do. It exists for reports that never made it past intake - a
dropped connection, a crashed request, a report seeded directly onto
disk - so nothing pending is silently forgotten.

Runnable two ways:
    python -m app.services.nightly_batch
    POST /api/v1/batch/run   (app/routers/batch.py)

Idempotent by construction: it only selects reports whose status is
still pending-like. process_report() moves a report out of that state
(to awaiting_approval or failed) before this function's own summary is
written, so re-running the batch immediately - or concurrently - does
not reprocess anything that already moved on.
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.services.report_intake import STORAGE_DIR
from app.services.report_pipeline import ReportPipelineError, process_report
from app.services.report_store import read_metadata

# Statuses considered "not yet processed". "received" is the status
# used by report dirs created before this metadata lifecycle existed;
# treated the same as "pending" so old, never-processed intake is
# still picked up rather than silently ignored forever.
PENDING_LIKE_STATUSES = {"pending", "received"}


def _default_batches_dir(storage_dir: Path) -> Path:
    return storage_dir.parent / "batches"


def _find_pending_reports(storage_dir: Path) -> list[Path]:
    if not storage_dir.exists():
        return []

    pending: list[Path] = []

    for report_dir in sorted(storage_dir.iterdir()):
        if not report_dir.is_dir():
            continue

        metadata_path = report_dir / "metadata.json"

        if not metadata_path.exists():
            continue

        try:
            metadata = read_metadata(report_dir)
        except (json.JSONDecodeError, OSError):
            continue

        if metadata.get("status") in PENDING_LIKE_STATUSES:
            pending.append(report_dir)

    return pending


async def _process_one(report_dir: Path) -> dict:
    report_id = report_dir.name
    metadata = read_metadata(report_dir)

    notes_path = report_dir / "notes.txt"
    notes = notes_path.read_text(encoding="utf-8") if notes_path.exists() else None
    photo_filenames = metadata.get("photos", [])

    if not notes and not photo_filenames:
        # Nothing to process - a report dir with no notes and no
        # photos on disk (e.g. an incomplete/corrupted intake). Don't
        # feed it to the pipeline; record it as skipped instead of
        # silently dropping it or crashing the batch.
        return {
            "report_id": report_id,
            "outcome": "skipped",
            "reason": "No notes.txt or photos found for a pending report.",
        }

    try:
        await process_report(
            report_id=report_id,
            report_dir=report_dir,
            notes=notes,
            photo_filenames=photo_filenames,
            explicit_project=metadata.get("project"),
        )
        return {"report_id": report_id, "outcome": "processed"}

    except ReportPipelineError as exc:
        # process_report() already marks metadata.status = "failed"
        # with a reason on this path - this is just for the batch's
        # own summary.
        return {
            "report_id": report_id,
            "outcome": "failed",
            "reason": str(exc),
        }

    except Exception as exc:
        return {
            "report_id": report_id,
            "outcome": "failed",
            "reason": f"Unexpected error: {exc}",
        }


async def run_nightly_batch(
    *,
    storage_dir: Path | None = None,
    batches_dir: Path | None = None,
) -> dict:
    """
    Process every pending-like report under storage_dir, one at a
    time. A failure in one report is caught and recorded - it never
    stops the rest of the batch.
    """

    storage_dir = storage_dir or STORAGE_DIR
    batches_dir = batches_dir or _default_batches_dir(storage_dir)
    batches_dir.mkdir(parents=True, exist_ok=True)

    pending_dirs = _find_pending_reports(storage_dir)

    results = []

    for report_dir in pending_dirs:
        # Sequential on purpose: SuperDocs sessions are per-report and
        # the API has already shown 409 session_busy under concurrent
        # jobs. Simple and safe beats fast here.
        result = await _process_one(report_dir)
        results.append(result)

    processed = [r for r in results if r["outcome"] == "processed"]
    failed = [r for r in results if r["outcome"] == "failed"]
    skipped = [r for r in results if r["outcome"] == "skipped"]

    summary = {
        "date": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates_found": len(pending_dirs),
        "processed_count": len(processed),
        "failed_count": len(failed),
        "skipped_count": len(skipped),
        "processed": processed,
        "failed": failed,
        "skipped": skipped,
    }

    summary_path = batches_dir / f"{summary['date']}.json"
    summary_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    return summary


async def _main() -> None:
    summary = await run_nightly_batch()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())
