"""Durable state for reports and in-flight runs.

Plain JSON files on disk. A database would buy concurrency guarantees this build
does not need, one report is edited by one person from one sidebar, and would
cost a stranger the "clone and run" property the brief asks for.

What it does need is to survive a crash: state is written after each stage, and
written atomically, so a process killed mid-run resumes instead of losing work
or leaving a half-written manifest behind.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
from typing import Any

from .models import ReportManifest


class ReportStore:
    """Filesystem-backed store for manifests and pending runs."""

    def __init__(self, root: pathlib.Path | str) -> None:
        self.root = pathlib.Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ paths

    def _dir(self, report_id: str) -> pathlib.Path:
        safe = "".join(c for c in report_id if c.isalnum() or c in "-_")
        if not safe:
            raise ValueError(f"unusable report id {report_id!r}")
        path = self.root / safe
        path.mkdir(parents=True, exist_ok=True)
        return path

    def manifest_path(self, report_id: str) -> pathlib.Path:
        return self._dir(report_id) / "manifest.json"

    def run_path(self, report_id: str) -> pathlib.Path:
        return self._dir(report_id) / "pending_run.json"

    # ------------------------------------------------------------------- I/O

    @staticmethod
    def _write_atomic(path: pathlib.Path, text: str) -> None:
        """Write via a temp file and rename, so a crash never truncates state."""
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        except BaseException:
            pathlib.Path(tmp).unlink(missing_ok=True)
            raise

    def load_manifest(self, report_id: str) -> ReportManifest | None:
        path = self.manifest_path(report_id)
        if not path.exists():
            return None
        return ReportManifest.from_json(path.read_text(encoding="utf-8"))

    def save_manifest(self, manifest: ReportManifest) -> None:
        self._write_atomic(self.manifest_path(manifest.report_id), manifest.to_json())

    def load_run(self, report_id: str) -> dict[str, Any] | None:
        path = self.run_path(report_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def save_run(self, report_id: str, state: dict[str, Any]) -> None:
        self._write_atomic(self.run_path(report_id), json.dumps(state, indent=2, sort_keys=True))

    def clear_run(self, report_id: str) -> None:
        self.run_path(report_id).unlink(missing_ok=True)

    def list_reports(self) -> list[str]:
        return sorted(p.name for p in self.root.iterdir() if (p / "manifest.json").exists())
