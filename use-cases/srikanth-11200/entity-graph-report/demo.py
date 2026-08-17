"""
Standalone SuperDocs integration demo for the "Entity-graph retrieval to a
structured report with a diagram" assigned build.

Drives the REAL upload -> chat/async -> poll -> approve -> export sequence
against the real SuperDocs API (https://api.superdocs.app) for one
already-approved report snapshot, loaded from fixtures/ rather than a
live database. Every SuperDocs-side step is a genuine network call
through superdocs_client.SuperDocsClient. The only local, offline work is
loading the fixtures and building the outline HTML / per-section
instructions (report_to_superdocs.ReportToSuperDocs), which is pure data
transformation over data DocTask (the private Task 1 system) already
produced and a human already approved.

This script does NOT connect to PostgreSQL, does NOT import any DocTask
model or service, does NOT require LangGraph, Groq, or ChromaDB, and does
NOT require the private DocTask repository to be present. Everything it
needs lives in this folder: fixtures/approved_sections.json and
fixtures/diagram.svg (both real, pre-generated snapshots - see this
folder's README for how they were produced).

Run from this directory, with SUPERDOCS_API_KEY set to a REAL SuperDocs
API key:

    pip install -r requirements.txt
    export SUPERDOCS_API_KEY=your-key-here
    python demo.py

If the fixture has zero approved sections, or zero approved sections with
an actual writable claim (all insufficient_evidence / empty body), this
script says so honestly and exits WITHOUT calling SuperDocs at all - no
SuperDocs operation is spent sending nothing.
"""

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

from report_to_superdocs import ApprovedSection, ReportToSuperDocs
from superdocs_client import SuperDocsAPIError, SuperDocsClient

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SECTIONS_FIXTURE = FIXTURES_DIR / "approved_sections.json"
DIAGRAM_FIXTURE = FIXTURES_DIR / "diagram.svg"

# A fresh, unique session id per run (rather than a fixed constant) so
# repeated runs never collide with - or silently continue editing - a
# previous run's SuperDocs session. A real caller could equally derive
# this from a report id, exactly as DocTask's own internal demo does;
# this standalone package has no report id of its own to key off, so a
# short uuid is the simplest honest choice.
SESSION_ID = f"entity-graph-report-demo-{uuid.uuid4().hex[:8]}"


def load_approved_sections() -> list[ApprovedSection]:
    with open(SECTIONS_FIXTURE, encoding="utf-8") as f:
        raw = json.load(f)
    return [
        ApprovedSection(
            section_index=item["section_index"],
            title=item["title"],
            body=item["body"],
            citations=item["citations"],
            insufficient_evidence=item["insufficient_evidence"],
        )
        for item in raw
    ]


def load_diagram_svg() -> str | None:
    if not DIAGRAM_FIXTURE.exists():
        return None
    text = DIAGRAM_FIXTURE.read_text(encoding="utf-8")
    return text if text.strip() else None


async def run() -> None:
    if not os.environ.get("SUPERDOCS_API_KEY"):
        print(
            "SUPERDOCS_API_KEY is not set. This demo makes real SuperDocs "
            "API calls and needs a real key.\n"
            "  export SUPERDOCS_API_KEY=your-key-here   (macOS/Linux)\n"
            "  $env:SUPERDOCS_API_KEY = 'your-key-here'  (PowerShell)"
        )
        sys.exit(1)

    sections = load_approved_sections()
    diagram_svg = load_diagram_svg()

    if not sections:
        print("fixtures/approved_sections.json: 0 approved sections. Nothing sent to SuperDocs.")
        return

    instructions = ReportToSuperDocs.build_instructions_for_report(sections)

    if not instructions:
        print(
            f"{len(sections)} approved section(s), but none has a writable, "
            f"evidence-backed claim (all insufficient_evidence or have an "
            f"empty body). Nothing sent to SuperDocs."
        )
        return

    client = SuperDocsClient.from_settings()

    # Task 2 "images" surface: upload the real, already-generated
    # relationship diagram as an image asset through SuperDocs' own
    # confirmed image endpoint (POST /v1/documents/images/upload-base64 -
    # SVG is a confirmed accepted format), then embed the real hosted URL
    # it returns in the outline. Never fabricated, never a data-URI guess
    # - if the upload fails or the response doesn't carry a recognizable
    # URL field, this is reported honestly and the outline still uploads
    # without the image rather than blocking the whole demo on an
    # optional step.
    diagram_image_url = None
    if diagram_svg:
        print("Uploading relationship diagram as an image asset...")
        try:
            image_response = await client.upload_image(content=diagram_svg.encode("utf-8"))
            diagram_image_url = ReportToSuperDocs.resolve_uploaded_image_url(image_response)
            if diagram_image_url:
                print(f"  Diagram image URL: {diagram_image_url}")
            else:
                print(
                    "  Image uploaded, but no recognizable URL field was "
                    f"found in the response: {image_response!r}. Proceeding "
                    "without embedding the diagram image."
                )
        except SuperDocsAPIError as exc:
            print(
                f"  Diagram image upload failed ({exc}). Proceeding without "
                "embedding the diagram image - this does not block the "
                "rest of the demo."
            )
    else:
        print("No diagram fixture found. Proceeding without a diagram image.")

    outline_html = ReportToSuperDocs.build_outline_html(sections, diagram_image_url=diagram_image_url)

    print(
        f"{len(sections)} approved section(s), {len(instructions)} with a "
        f"writable claim."
    )
    print(f"Uploading outline (session_id={SESSION_ID})...")
    await client.upload_document(
        filename="entity-graph-report-outline.html",
        content=outline_html.encode("utf-8"),
        session_id=SESSION_ID,
    )

    for instruction in instructions:
        print(f"Section {instruction.section_index} ({instruction.title!r}): sending chat instruction...")
        job_id = await client.start_chat_async(
            session_id=SESSION_ID,
            message=instruction.instruction,
        )
        job = await client.poll_job_until_done(job_id)

        if job.get("status") == "awaiting_approval":
            awaiting_kind = job.get("metadata", {}).get("awaiting_kind")

            if awaiting_kind == "continue_prompt":
                # Confirmed distinct pause reason: a large edit that
                # applied part of itself and is asking whether to
                # continue - not a HITL change review. This scope does
                # not auto-continue a multi-turn edit; report and move on
                # rather than guessing an answer.
                print(
                    f"  Section {instruction.section_index}: SuperDocs paused "
                    f"mid-edit (continue_prompt), not a change review - "
                    f"skipping approval for this section (out of scope)."
                )
                continue

            pending_changes = job.get("metadata", {}).get("pending_changes", [])
            print(f"  Approving {len(pending_changes)} proposed change(s)...")
            await client.approve_all_pending_changes(
                session_id=SESSION_ID,
                job_id=job_id,
                pending_changes=pending_changes,
            )
            job = await client.poll_job_until_done(job_id)

        if job.get("status") == "completed":
            print(f"  Section {instruction.section_index}: done.")
        else:
            print(
                f"  Section {instruction.section_index}: job ended with "
                f"status={job.get('status')!r} error={job.get('error')!r}"
            )

    print("Exporting final document...")
    exported = await client.export_document(session_id=SESSION_ID, format="docx")

    output_path = "entity-graph-report-export.docx"
    with open(output_path, "wb") as f:
        f.write(exported)

    print(f"Exported to {output_path}.")
    print(
        "Note: SuperDocs' docx exporter currently drops embedded images "
        "(a known, reported SuperDocs-side limitation - see README.md). "
        "Use format='html' if you need to verify the diagram is present "
        "in this session."
    )


if __name__ == "__main__":
    asyncio.run(run())
