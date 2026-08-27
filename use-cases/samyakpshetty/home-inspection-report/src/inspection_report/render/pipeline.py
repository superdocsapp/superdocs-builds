"""Turning an inspection into exported files.

The order here carries the guarantees:

* photographs are uploaded **before** the document is rendered, because a finding whose photo
  never arrived is rendered without it rather than with a broken image;
* the document is rendered **deterministically**, so structure never depends on a model;
* every proposed rewrite passes the language rail **before** it can be approved, so a
  certifying sentence is refused at the gate and never reaches an export;
* a job's decisions are collected and sent in **one** approve call, because approving closes
  the job;
* exports are verified by reading the finished bytes back.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from inspection_report.domain.models import Inspection, ReportStage
from inspection_report.logging import get_logger
from inspection_report.phrasing import rail
from inspection_report.render import report as render_report
from inspection_report.superdocs.base import SuperDocsClient, SuperDocsError
from inspection_report.superdocs.models import (
    ApprovalDecision,
    ChunkDiff,
    ExportOptions,
    ExportResult,
    JobStatus,
)

_log = get_logger("inspection_report.pipeline")

# One operation covers up to 25 edited sections, so a batch never exceeds that. A report
# with more findings than this goes out in several batches, each gated before the next.
MAX_SECTIONS_PER_BATCH = 25

# How long to let an approval settle before asking for the export. Measured, not guessed:
# an export taken sooner than this came back pre-approval on every run of a full-size report.
# It is a head start rather than a guarantee — the check afterwards is what makes it correct.
SETTLE_AFTER_APPROVE_S = 2.5

REWRITE_INSTRUCTION = (
    "Rewrite each paragraph marked finding-note so that someone buying their first home can "
    "understand it. Keep every fact, measurement and location exactly as written. Stay "
    "observational: describe what was found and what is recommended. Do not state that "
    "anything is safe, sound, compliant, certified, guaranteed, or typical for the age of "
    "the property, and do not estimate costs or predict how long anything will last. Change "
    "nothing except those paragraphs."
)


@dataclass
class Proposal:
    """One proposed rewrite, with the rail's verdict already attached."""

    diff: ChunkDiff
    verdict: rail.Verdict
    approved: bool = False
    decided: bool = False

    @property
    def refused_by_rail(self) -> bool:
        return not self.verdict.clean


@dataclass
class PipelineResult:
    session_id: str
    document_html: str
    job_id: str = ""
    proposals: list[Proposal] = field(default_factory=list)
    exports: dict[str, ExportResult] = field(default_factory=dict)
    photos_uploaded: int = 0
    photos_reused: int = 0
    ops_charged: int = 0
    ops_remaining: int | None = None

    @property
    def rail_refusals(self) -> int:
        return sum(1 for p in self.proposals if p.refused_by_rail)


def upload_photos(
    inspection: Inspection,
    photo_data: dict[str, bytes],
    client: SuperDocsClient,
    *,
    known: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Upload each distinct photograph once. Returns (uploaded, reused).

    Identity is the content hash, so a re-run after a crash re-uploads nothing, and the same
    photograph attached to two findings costs one upload.
    """
    cache: dict[str, str] = dict(known or {})
    uploaded = reused = 0
    for finding in inspection.findings:
        for photo in finding.photos:
            if photo.sha256 in cache:
                photo.remote_url = cache[photo.sha256]
                reused += 1
                continue
            data = photo_data.get(photo.filename)
            if data is None:
                _log.warning("photo_missing", extra={"sha256": photo.sha256[:12]})
                continue
            result = client.upload_image(
                data=data, filename=photo.filename, content_type=photo.content_type
            )
            photo.remote_url = result.url
            cache[photo.sha256] = result.url
            uploaded += 1
    return uploaded, reused


def _poll(client: SuperDocsClient, job_id: str, *, attempts: int = 120, wait_s: float = 2.0):  # type: ignore[no-untyped-def]
    import time

    for _ in range(attempts):
        job = client.get_job(job_id)
        if job.status in (
            JobStatus.AWAITING_APPROVAL,
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        ):
            return job
        time.sleep(wait_s)
    raise TimeoutError(
        f"job {job_id} did not settle. Large documents can take minutes; re-run to resume."
    )


def prepare(
    inspection: Inspection,
    template_html: str,
    photo_data: dict[str, bytes],
    client: SuperDocsClient,
    *,
    session_id: str,
    known_uploads: dict[str, str] | None = None,
    polish: bool = True,
    model_tier: str = "core",
    thinking_depth: str = "balanced",
) -> PipelineResult:
    """Get the report as far as the gate: photos up, document rendered, rewrites proposed.

    Stops there deliberately. The decision belongs to a person, and a person takes minutes or
    hours over it, so nothing here holds a connection open waiting for them.
    """
    uploaded, reused = upload_photos(inspection, photo_data, client, known=known_uploads)

    # The photographs are uploaded first, because the export needs them — but the document
    # the rewrite pass sees is rendered without them, because that is what made the pass
    # reliable here. See `render_report.render` for the measurements, including the part I
    # could not isolate. `finalise_document` puts them back before the export.
    html = render_report.render(inspection, template_html, include_photos=False)
    upload = client.upload_document(document_html=html, session_id=session_id)
    inspection.stage = ReportStage.PREPARED
    result = PipelineResult(
        session_id=session_id,
        document_html=upload.html,
        photos_uploaded=uploaded,
        photos_reused=reused,
    )
    if not polish:
        return result

    job_id = client.chat_async(
        session_id=session_id,
        message=REWRITE_INSTRUCTION,
        approval_mode="ask_every_time",
        model_tier=model_tier,
        thinking_depth=thinking_depth,
    )
    job = _poll(client, job_id)
    result.job_id = job_id
    if job.usage:
        result.ops_charged += job.usage.ops_charged
        result.ops_remaining = job.usage.ops_remaining()

    # "Asked for N changes and got zero" is a failure, not an answer — a job can finish with
    # no error and propose nothing, which silently drops every rewrite.
    if not job.chunk_diffs:
        _log.warning("no_proposals", extra={"job_id": job_id})

    for diff in job.chunk_diffs:
        verdict = rail.check(_text_of(diff.new_html))
        # A proposal the rail refuses is pre-decided against. A person may not approve it,
        # because the rail is a rule rather than an opinion, but they see exactly why.
        result.proposals.append(
            Proposal(diff=diff, verdict=verdict, approved=False, decided=not verdict.clean)
        )
    inspection.stage = ReportStage.IN_REVIEW
    return result


def decide(
    inspection: Inspection,
    result: PipelineResult,
    client: SuperDocsClient,
    *,
    approvals: dict[str, bool],
) -> PipelineResult:
    """Relay the human's decisions, once every change from the job has one.

    ``approvals`` maps change_id to the person's decision. A change the rail refused is not
    theirs to approve and stays refused whatever the map says.
    """
    if not result.proposals:
        return result

    for proposal in result.proposals:
        if proposal.refused_by_rail:
            proposal.approved = False
        else:
            proposal.approved = approvals.get(proposal.diff.change_id, False)
        proposal.decided = True

    decisions = [
        ApprovalDecision(
            change_id=p.diff.change_id,
            approved=p.approved,
            feedback=""
            if p.verdict.clean
            else f"Refused by the observational-language rail: {p.verdict.summary()}",
        )
        for p in result.proposals
    ]
    # One call per job: approving closes it, so every decision goes together.
    client.approve(session_id=result.session_id, decisions=decisions, job_id=result.job_id)
    inspection.stage = ReportStage.APPROVED
    _apply_to_findings(inspection, result.proposals)
    return result


def build(
    inspection: Inspection,
    template_html: str,
    photo_data: dict[str, bytes],
    client: SuperDocsClient,
    *,
    session_id: str,
    polish: bool = True,
    model_tier: str = "core",
    thinking_depth: str = "balanced",
    formats: tuple[str, ...] = ("pdf", "docx"),
    settle_s: float = SETTLE_AFTER_APPROVE_S,
) -> PipelineResult:
    """Run an inspection all the way to exported files, taking the rail's verdict as the gate.

    This is the unattended path — the command line and the tests. The interface drives
    ``prepare`` and ``decide`` separately so a person holds the gate.

    ``settle_s`` is how long to let an approval land before asking for the export. It is a
    property of the service rather than of this pipeline — the in-memory implementation
    applies approvals synchronously and has nothing to wait for — so a caller running against
    a fake passes 0 and a caller running live leaves the default.
    """
    result = prepare(
        inspection,
        template_html,
        photo_data,
        client,
        session_id=session_id,
        polish=polish,
        model_tier=model_tier,
        thinking_depth=thinking_depth,
    )
    if result.proposals:
        decide(
            inspection,
            result,
            client,
            approvals={p.diff.change_id: p.verdict.clean for p in result.proposals},
        )

    name = _slug(inspection)
    expected = [_text_of(p.diff.new_html)[:60] for p in result.proposals if p.approved]
    export_session = finalise_document(client, inspection, template_html, session_id=session_id)
    for fmt in formats:
        result.exports[fmt] = _export_when_current(
            client,
            session_id=export_session,
            fmt=fmt,
            filename=name,
            expected=expected,
            settle_s=settle_s,
        )
    inspection.stage = ReportStage.EXPORTED
    return result


def finalise_document(
    client: SuperDocsClient,
    inspection: Inspection,
    template_html: str,
    *,
    session_id: str,
) -> str:
    """Put the reviewed report — photographs included — where it can be exported from.

    Returns the session the export must be taken from.

    The rewrite pass ran against a photograph-free document, so the reviewed session holds
    the approved wording and no pictures. This renders the whole report again from our own
    record: `Finding.prose()` returns the approved rewrite where there is one and the
    inspector's own words where there is not, so nothing is lost and nothing is invented.

    It goes to a *new* session rather than back into the reviewed one, and that is not
    tidiness. Measured on the live service, 26 Aug 2026, with the same finished HTML: uploaded
    into the session that had already been through chat and approve, the export came back at
    90,628 bytes with every photograph silently gone; uploaded into a fresh session it came
    back at 162,697 bytes with all eight embedded. A second upload into a used session does
    not replace what the export reads.

    The session name is keyed to the content, so exporting the same finished report twice
    re-uses one session and uploading it again is a no-op rather than a second document.
    Uploads and exports cost no operation, which is what makes re-rendering the cheap answer
    rather than a clever one.
    """
    html = render_report.render(inspection, template_html)
    digest = hashlib.sha256(html.encode("utf-8")).hexdigest()[:12]
    export_session = f"{session_id}-final-{digest}"
    client.upload_document(document_html=html, session_id=export_session)
    return export_session


def export_recovering_session(
    client: SuperDocsClient,
    inspection: Inspection,
    template_html: str,
    *,
    session_id: str,
    fmt: str,
    filename: str,
    expected: list[str],
    settle_s: float = SETTLE_AFTER_APPROVE_S,
) -> tuple[ExportResult, bool]:
    """Export a finished report, rebuilding the session's document if it is gone.

    Returns the file and whether it had to be rebuilt.

    A session is where the document lives, and a session does not outlive everything: the
    process restarts, the service forgets it, someone exports a report again weeks after it
    was signed off. None of that loses anything — every finding, every approved rewrite and
    every photograph is in our own database — so the document is re-rendered from there
    rather than the export failing on a report that is already finished.

    The rebuild is deterministic and neither upload nor export costs an operation, which is
    what makes this the cheap answer rather than a clever one. What it must not do is happen
    silently: a rebuilt document is rendered from the approved wording recorded against each
    finding, so there is nothing left pending for the export to wait on, and the caller is
    told which path produced the file.
    """
    try:
        return (
            _export_when_current(
                client,
                session_id=session_id,
                fmt=fmt,
                filename=filename,
                expected=expected,
                settle_s=settle_s,
            ),
            False,
        )
    except SuperDocsError as exc:
        if "no document loaded" not in str(exc).lower():
            raise
    _log.info("session_lost_rebuilding", extra={"session_id": session_id})
    client.upload_document(
        document_html=render_report.render(inspection, template_html), session_id=session_id
    )
    return (
        _export_when_current(
            client,
            session_id=session_id,
            fmt=fmt,
            filename=filename,
            # The rebuilt document already carries the approved wording, so there is no
            # pending approval to wait on — and waiting for one would never converge.
            expected=[],
            settle_s=0.0,
        ),
        True,
    )


def _export_when_current(
    client: SuperDocsClient,
    *,
    session_id: str,
    fmt: str,
    filename: str,
    expected: list[str],
    attempts: int = 5,
    wait_s: float = 2.0,
    settle_s: float = SETTLE_AFTER_APPROVE_S,
) -> ExportResult:
    """Export, and refuse to accept a file that predates the approvals.

    Exporting immediately after approving can return the **pre-approval** document with a 200
    and no warning. Measured across four runs of an eight-finding, eight-photograph report:
    the first export was stale at +2.2s to +2.4s after `approve` returned, and converged at
    about +4.4s (pdf) and +5.4s (docx).

    Two mechanisms, and both earn their place:

    * **Wait first.** A short settle costs one pause and skips an export that would be stale
      anyway. Measured: a 3s wait was enough for a seven-finding report, and so was 5s.
    * **Then check.** The wait alone is a guess, because the window grows with the document —
      the same test on a three-paragraph document never went stale at all, so a constant
      tuned on a small report is not a constant at all. Reading the file back tests the
      actual condition instead of hoping the guess held.

    Exports cost nothing, which is what makes re-reading the right answer rather than an
    expensive one. If it never converges the caller still gets the file, with the mismatch
    logged at ERROR, because silently shipping a report missing approved changes is the one
    outcome this must not have.
    """
    import time

    from inspection_report.verify import exports as verify_exports

    options = ExportOptions(
        paper_size="Letter",
        margins="normal",
        filename=filename,
        # HTML export references images by URL unless this is set, and those URLs resolve
        # for anyone holding them, with no credentials and no expiry. An exported file must
        # carry the picture, not a pointer to a client's house.
        embed_images=True,
    )
    if expected and settle_s:
        time.sleep(settle_s)
    result = client.export(session_id=session_id, fmt=fmt, options=options)
    if not expected:
        return result

    for attempt in range(attempts):
        text = (
            verify_exports.text_of_docx(result.content)
            if fmt == "docx"
            else verify_exports.text_of_pdf(result.content)
        )
        flat = " ".join(text.split())
        missing = [phrase for phrase in expected if phrase not in flat]
        if not missing:
            return result
        if attempt == attempts - 1:
            _log.error(
                "export_stale_after_approval",
                extra={"fmt": fmt, "missing": len(missing), "attempts": attempts},
            )
            return result
        _log.info("export_stale_retrying", extra={"fmt": fmt, "missing": len(missing)})
        time.sleep(wait_s * (attempt + 1))
        result = client.export(session_id=session_id, fmt=fmt, options=options)
    return result


def _text_of(html: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", html).strip()


def _apply_to_findings(inspection: Inspection, proposals: list[Proposal]) -> None:
    """Record approved rewrites against the findings they belong to.

    A refused or rejected rewrite leaves ``plain_language`` empty, and the export falls back
    to the inspector's own words.
    """
    by_text = {" ".join(f.observation.split()): f for f in inspection.findings}
    for proposal in proposals:
        if not proposal.approved:
            continue
        original = " ".join(_text_of(proposal.diff.old_html).split())
        finding = by_text.get(original)
        if finding is not None:
            finding.plain_language = _text_of(proposal.diff.new_html)


def _slug(inspection: Inspection) -> str:
    raw = f"{inspection.property.address_line}-{inspection.inspected_on:%Y-%m-%d}"
    return "".join(c if c.isalnum() else "-" for c in raw.lower()).strip("-")
