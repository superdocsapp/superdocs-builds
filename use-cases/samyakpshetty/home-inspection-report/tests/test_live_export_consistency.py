"""A runnable reproduction of the export-after-approve race.

Marked ``live``, so it never runs in the keyless suite. It exists so the finding can be
checked rather than believed:

    SUPERDOCS_API_KEY=... pytest -m live

What it asserts is deliberately weak — that an export taken immediately after approval either
already reflects the approval, or converges within a few seconds. A service that fixes the
race keeps passing. What it *reports*, on failure and on success, is the timing, because the
timing is the finding.

Observed on 15 Aug 2026, four consecutive runs with an eight-finding, eight-photograph
document: the first export completed +2.18s to +2.43s after `approve` returned 200 and carried
the **pre-approval** text every time, converging at +4.4s (pdf) and +5.4s (docx). The same
document with three paragraphs and no images converged before +2.8s and never showed the
stale state — the window scales with document size.
"""

from __future__ import annotations

import base64
import json
import os
import time

import pytest

pytestmark = pytest.mark.live

MARKER = "REWRITTEN"
SYSTEMS = ["Roof", "Electrical", "Plumbing", "Heating", "Structure", "Exterior"]


@pytest.fixture(scope="module")
def client():  # type: ignore[no-untyped-def]
    from inspection_report.superdocs.live import LiveSuperDocsClient

    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if not key:
        pytest.skip("needs SUPERDOCS_API_KEY")
    c = LiveSuperDocsClient(api_key=key)
    yield c
    c.close()


def _document(client) -> str:  # type: ignore[no-untyped-def]
    """A document of the size that shows the race: several findings, each with a photograph."""
    parts = ["<h1>Export consistency probe</h1>"]
    for i, system in enumerate(SYSTEMS):
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAEUlEQVR4nGP8z4"
            "AAjAxDVQAAA//8DAAKgAWNU3AAAAABJRU5ErkJggg=="
        )
        upload = client.upload_image(data=png, filename=f"p{i}.png")
        parts.append(
            f"<h2>{system}</h2>"
            f"<p class='finding-note'>ORIGINAL-{i:02d} field note for {system.lower()}.</p>"
            f"<p><img src='{upload.url}' alt='{system}'></p>"
        )
    return "".join(parts)


def test_an_export_taken_immediately_after_approve_reflects_the_approval(client) -> None:  # type: ignore[no-untyped-def]
    from inspection_report.superdocs.models import ApprovalDecision
    from inspection_report.verify.exports import text_of_pdf

    session = f"consistency-{int(time.time())}"
    client.upload_document(document_html=_document(client), session_id=session)

    job_id = client.chat_async(
        session_id=session,
        message=(
            f"Rewrite every paragraph with class finding-note so it begins with the word "
            f"{MARKER}. Change nothing else."
        ),
        approval_mode="ask_every_time",
    )
    job = None
    for _ in range(120):
        time.sleep(2)
        job = client.get_job(job_id)
        if job.status in ("awaiting_approval", "completed", "failed"):
            break
    assert job is not None and job.chunk_diffs, "no proposals came back; cannot test approval"

    client.approve(
        session_id=session,
        job_id=job_id,
        decisions=[ApprovalDecision(change_id=d.change_id, approved=True) for d in job.chunk_diffs],
    )
    approved_at = time.time()

    timeline = []
    converged_at = None
    for _ in range(15):
        export = client.export(session_id=session, fmt="pdf")
        elapsed = time.time() - approved_at
        current = MARKER in text_of_pdf(export.content)
        timeline.append({"at": round(elapsed, 2), "current": current})
        if current:
            converged_at = elapsed
            break
        time.sleep(1.0)

    print("\nexport timeline after approve returned 200:")
    print(json.dumps(timeline, indent=2))

    stale = [t for t in timeline if not t["current"]]
    if stale:
        print(
            f"\nRACE OBSERVED: the export served the pre-approval document until "
            f"+{stale[-1]['at']}s, converging at +{converged_at:.2f}s. "
            f"This is why the pipeline re-reads an export before accepting it."
        )

    assert converged_at is not None, (
        "the export never reflected the approved changes. Approving returned 200, so a "
        "caller trusting that would ship a document missing every approved edit."
    )
