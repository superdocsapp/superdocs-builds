"""Shared configuration: each quickstart differs only at the binding boundary."""

from __future__ import annotations

import os
from pathlib import Path

from superdocs_adapter import SuperDocsAdapter, SuperDocsClient, SuperDocsToolset
from superdocs_adapter.models import Job

ROOT = Path(__file__).resolve().parents[1]
INPUT_FILE = ROOT / "examples" / "input" / "sample-policy.txt"
INSTRUCTION = (
    "Replace the exact sentence 'Support is available on weekdays.' with "
    "'Support is available Monday through Friday, 09:00-17:00 UTC.' "
    "Do not change anything else."
)
ARGUMENTS = {
    "file_path": str(INPUT_FILE),
    "instruction": INSTRUCTION,
    "output_format": "txt",
}


def build_toolset(output_directory: Path) -> SuperDocsToolset:
    api_key = os.environ.get("SUPERDOCS_API_KEY", "")
    client = SuperDocsClient(api_key)
    adapter = SuperDocsAdapter(client, timeout=600)
    last_seen: tuple[str, int] | None = None

    def show_progress(job: Job) -> None:
        nonlocal last_seen
        current = (job.status.value, job.progress)
        if current != last_seen:
            print(f"[SuperDocs] {job.status.value}: {job.progress}%")
            last_seen = current

    return SuperDocsToolset(
        adapter,
        output_directory=output_directory,
        on_progress=show_progress,
    )
