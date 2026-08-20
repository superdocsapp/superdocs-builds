"""Orchestrates one battlecard: fill the known fields locally, upload,
ask SuperDocs for the one sentence that needs real synthesis, export.

Deliberately a plain function, not a class with state -- each call is a
fresh session against a fresh copy of the template, so two competitors run
back to back can never bleed content into each other.
"""

from dataclasses import dataclass
from pathlib import Path

from .superdocs_client import SuperDocsClient
from .template import build_filled_template_bytes


@dataclass
class CompetitorInput:
    name: str
    likely_pitch: str
    where_we_win: str
    where_we_dont: str


def _build_instruction(competitor: CompetitorInput) -> str:
    """Scoped to exactly one section on purpose -- see template.py's module
    docstring for why the other three fields are filled in locally instead
    of asked of the model."""
    return (
        f'Replace the placeholder text under the "Talk Track" heading with a single short '
        f"sentence a sales rep could say out loud when a prospect brings up {competitor.name}. "
        f"Base it only on these two points, don't invent new claims: "
        f'we win because "{competitor.where_we_win}"; they\'re stronger because '
        f'"{competitor.where_we_dont}". Do not change any other section, heading, or the title.'
    )


def generate_battlecard(
    client: SuperDocsClient,
    competitor: CompetitorInput,
    output_dir: Path,
    export_format: str = "docx",
) -> Path:
    """Runs one competitor through the full real flow and writes the
    exported file to output_dir. Returns the path written."""
    template_bytes = build_filled_template_bytes(
        competitor_name=competitor.name,
        likely_pitch=competitor.likely_pitch,
        where_we_win=competitor.where_we_win,
        where_we_dont=competitor.where_we_dont,
    )

    upload = client.upload_document(
        file_bytes=template_bytes,
        filename=f"battlecard-{competitor.name}.docx",
    )

    instruction = _build_instruction(competitor)
    job = client.start_edit(session_id=upload.session_id, instruction=instruction)
    status = client.wait_for_completion(job.job_id)

    if status.status == "awaiting_approval":
        client.approve(session_id=upload.session_id, job_id=job.job_id, approved=True)
    elif status.status == "failed":
        raise RuntimeError(f"edit failed for {competitor.name}: {status.raw}")
    # status.status == "completed" already -- calling approve() here would
    # 400 (verified live against the real API on a different SuperDocs build).

    export = client.export(session_id=upload.session_id, format=export_format)

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in competitor.name)
    out_path = output_dir / f"battlecard-{safe_name}.{export_format}"
    out_path.write_bytes(export.file_bytes)
    return out_path
