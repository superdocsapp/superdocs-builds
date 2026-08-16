"""
Shared read/write helpers for a report's on-disk metadata and
structured data.

This is the index that nightly batching and the weekly rollup query
directly, so writes go through here rather than each caller hand-rolling
its own json.dumps/loads.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.models.field_report import FieldReportData
from app.services.report_intake import STORAGE_DIR

# Status lifecycle: pending -> processing -> awaiting_approval ->
# approved -> exported, with failed reachable from processing.
STATUSES = {
    "pending",
    "processing",
    "awaiting_approval",
    "approved",
    "exported",
    "failed",
}

TERMINAL_STATUSES = {"exported", "failed"}


def metadata_path(report_dir: Path) -> Path:
    return report_dir / "metadata.json"


def report_json_path(report_dir: Path) -> Path:
    return report_dir / "report.json"


def read_metadata(report_dir: Path) -> dict:
    path = metadata_path(report_dir)
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, content: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def write_metadata(report_dir: Path, metadata: dict) -> None:
    _atomic_write(
        metadata_path(report_dir),
        json.dumps(metadata, indent=2),
    )


def update_metadata(report_dir: Path, **updates) -> dict:
    """Read-merge-write. Last writer wins; callers own their own locking."""

    metadata = read_metadata(report_dir)
    metadata.update(updates)
    write_metadata(report_dir, metadata)
    return metadata


def write_report_json(report_dir: Path, report: FieldReportData) -> None:
    _atomic_write(
        report_json_path(report_dir),
        json.dumps(report.model_dump(mode="json"), indent=2),
    )


def read_report_json(report_dir: Path) -> dict | None:
    path = report_json_path(report_dir)

    if not path.exists():
        return None

    return json.loads(path.read_text(encoding="utf-8"))


def list_report_dirs() -> list[Path]:
    if not STORAGE_DIR.exists():
        return []

    return sorted(
        p for p in STORAGE_DIR.iterdir() if p.is_dir()
    )
