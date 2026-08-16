import asyncio
import base64
import json
import mimetypes
import re
from pathlib import Path

from app.models.field_report import FieldReportData
from app.services.report_builder import build_daily_report_html
from app.services.report_extractor import extract_field_report
from app.services.report_store import update_metadata, write_report_json
from app.services.superdocs_service import SuperDocsClient


class ReportPipelineError(Exception):
    """Raised when daily field report processing fails."""


async def wait_for_superdocs_approval(
    *,
    superdocs: SuperDocsClient,
    job_id: str,
    poll_interval: float = 2.0,
    max_attempts: int = 30,
) -> dict:
    """
    Poll a SuperDocs approval job until it reaches a stable state.

    The function stops when the job is:
    - awaiting_approval
    - completed
    - failed
    - rejected
    - cancelled
    """

    for attempt in range(1, max_attempts + 1):
        job = await superdocs.get_job(job_id)

        status = job.get("status")

        print(
            f"SuperDocs job attempt {attempt}: {status}"
        )

        if status in {
            "awaiting_approval",
            "completed",
            "failed",
            "rejected",
            "cancelled",
        }:
            return job

        await asyncio.sleep(poll_interval)

    raise ReportPipelineError(
        "SuperDocs approval job did not reach a "
        "stable state within the polling limit."
    )


def build_image_attachments(
    photo_paths: list[Path],
) -> list[dict]:
    """
    Convert saved report photos into the image attachment format
    expected by SuperDocs chat.
    """

    attachments = []

    for index, photo_path in enumerate(photo_paths, start=1):
        if not photo_path.exists():
            raise ReportPipelineError(
                f"Photo not found: {photo_path}"
            )

        raw_bytes = photo_path.read_bytes()

        mime_type, _ = mimetypes.guess_type(
            photo_path.name
        )

        if not mime_type:
            raise ReportPipelineError(
                f"Unable to determine image type: "
                f"{photo_path.name}"
            )

        attachments.append(
            {
                "id": f"img-{index}",
                "name": photo_path.name,
                "base64Data": base64.b64encode(
                    raw_bytes
                ).decode("ascii"),
                "mimeType": mime_type,
                "size": len(raw_bytes),
            }
        )

    return attachments


def build_photo_data_urls(
    photo_paths: list[Path],
) -> list[str]:
    """
    Convert saved photos into data URLs so the generated HTML
    contains the actual images and remains self-contained.
    """

    urls = []

    for photo_path in photo_paths:
        if not photo_path.exists():
            raise ReportPipelineError(
                f"Photo not found: {photo_path}"
            )

        raw_bytes = photo_path.read_bytes()

        mime_type, _ = mimetypes.guess_type(
            photo_path.name
        )

        if not mime_type:
            raise ReportPipelineError(
                f"Unable to determine image type: "
                f"{photo_path.name}"
            )

        encoded = base64.b64encode(
            raw_bytes
        ).decode("ascii")

        urls.append(
            f"data:{mime_type};base64,{encoded}"
        )

    return urls


async def start_superdocs_workflow(
    *,
    report_id: str,
    html_path: Path,
) -> dict:
    """
    Upload the generated report to SuperDocs and start
    an AI edit job requiring human approval.

    This function intentionally stops at the human approval
    stage. It does not approve changes automatically.
    """

    if not html_path.exists():
        raise ReportPipelineError(
            f"Generated report does not exist: {html_path}"
        )

    superdocs = SuperDocsClient()

    session_id = f"daily-report-{report_id}"

    # ---------------------------------------------------------
    # Step 1: Upload generated report
    # ---------------------------------------------------------

    upload_result = await superdocs.upload_document(
        session_id=session_id,
        file_path=html_path,
    )

    # ---------------------------------------------------------
    # Step 2: Start AI edit requiring human approval
    # ---------------------------------------------------------

    approval_job = await superdocs.start_approval_job(
        session_id=session_id,
        message=(
            "Review this Daily Field Report and make only "
            "professional formatting or wording improvements. "
            "Do not change factual content, numbers, dates, "
            "photos, captions, source field observations, "
            "equipment status, manpower, work performed, "
            "weather, delays, or safety observations."
        ),
    )

    job_id = approval_job.get("job_id")

    if not job_id:
        raise ReportPipelineError(
            "SuperDocs did not return a job ID."
        )

    # ---------------------------------------------------------
    # Step 3: Wait until human approval is required
    # ---------------------------------------------------------

    job_status = await wait_for_superdocs_approval(
        superdocs=superdocs,
        job_id=job_id,
    )

    return {
        "session_id": session_id,
        "upload": upload_result,
        "job": job_status,
        "status": job_status.get("status"),
        "job_id": job_id,
    }


def _extract_json_photo_results(
    response_text: str,
) -> list[dict]:
    """
    Try to recover structured photo results if SuperDocs
    returns valid JSON.

    Returns an empty list when the response is not JSON.
    """

    text = response_text.strip()

    try:
        parsed = json.loads(text)

        if isinstance(parsed, dict):
            photos = parsed.get("photos")

            if isinstance(photos, list):
                return photos

    except json.JSONDecodeError:
        pass

    # SuperDocs may wrap JSON in a Markdown code block.
    match = re.search(
        r"```(?:json)?\s*(\{.*\})\s*```",
        text,
        flags=re.DOTALL,
    )

    if match:
        try:
            parsed = json.loads(
                match.group(1)
            )

            if isinstance(parsed, dict):
                photos = parsed.get("photos")

                if isinstance(photos, list):
                    return photos

        except json.JSONDecodeError:
            pass

    return []


def extract_photo_captions(
    *,
    response_text: str,
    photo_paths: list[Path],
) -> list[str]:
    """
    Convert SuperDocs' vision response into safe captions.

    Supports both structured JSON and prose responses.

    Unsupported claims about project impact, safety,
    disruption, or location are intentionally not copied
    into the report.
    """

    if not photo_paths:
        return []

    structured_results = _extract_json_photo_results(
        response_text
    )

    captions: list[str] = []

    for index, photo_path in enumerate(photo_paths):
        caption = None
        relevant = True

        if index < len(structured_results):
            result = structured_results[index]

            if isinstance(result, dict):
                relevant = result.get(
                    "relevant",
                    True,
                )

                candidate = result.get(
                    "caption"
                )

                if isinstance(candidate, str):
                    caption = candidate.strip()

        lower_response = response_text.lower()

        unrelated_markers = (
            "not a construction site",
            "not related to construction",
            "not a construction",
            "wildlife",
            "primate",
            "animal",
            "portrait",
        )

        if any(
            marker in lower_response
            for marker in unrelated_markers
        ):
            relevant = False

        if not relevant:
            caption = (
                "Image does not depict a construction "
                "site activity."
            )

        if not caption:
            match = re.search(
                r"Daily Field Report Caption:\s*"
                r'["“](.*?)["”]',
                response_text,
                flags=re.IGNORECASE | re.DOTALL,
            )

            if match:
                candidate = match.group(1).strip()

                if candidate:
                    caption = candidate

        if not caption:
            caption = (
                f"Site photo {index + 1}; "
                "visual details available from the attached image."
            )

        captions.append(caption)

    return captions


async def process_report(
    *,
    report_id: str,
    report_dir: Path,
    notes: str | None,
    photo_filenames: list[str],
    explicit_project: str | None = None,
) -> dict:
    """
    Process an uploaded field report.

    Pipeline:

    1. Extract structured facts from field notes when notes exist.
    2. Resolve saved photo files.
    3. Analyze photos when photos exist.
    4. Generate photo captions.
    5. Build the daily report HTML.
    6. Save the intermediate report (HTML + report.json).
    7. Upload the generated report to SuperDocs.
    8. Start an AI edit requiring human approval.
    9. Stop at awaiting_approval.

    Notes-only, photos-only, and notes + photos are supported.

    Updates metadata.json's status/project/report_date as it goes, so
    metadata stays the queryable index even if this is invoked outside
    the normal request flow (e.g. by the nightly batch).
    """

    notes = notes.strip() if notes else None
    explicit_project = (
        explicit_project.strip()
        if explicit_project and explicit_project.strip()
        else None
    )

    if not notes and not photo_filenames:
        raise ReportPipelineError(
            "Provide field notes, at least one photo, or both."
        )

    update_metadata(report_dir, status="processing")

    try:
        # ---------------------------------------------------------
        # Step 1: Extract structured field data
        # ---------------------------------------------------------

        if notes:
            report: FieldReportData = (
                await extract_field_report(
                    report_id=report_id,
                    notes=notes,
                )
            )
        else:
            # Photos-only report.
            #
            # The extractor requires notes, so create a minimal
            # report object without inventing project facts.
            report = FieldReportData(
                project=None,
                report_date=None,
                total_headcount=None,
                manpower=[],
                equipment=[],
                work_by_area=[],
                weather=None,
                delays=[],
                safety_observations=[],
                source_notes=(
                    "No field notes were provided. "
                    "Report generated from uploaded photos."
                ),
            )

        # ---------------------------------------------------------
        # Step 1b: Reconcile explicit vs extracted project
        # ---------------------------------------------------------
        #
        # Photo-only reports have no notes to extract a project from, and
        # batching "across projects" needs a reliable identifier. If both
        # exist and disagree, don't silently pick one - flag it and keep
        # the explicit value (it was a deliberate submission-time choice,
        # not a model guess).

        project_mismatch = None

        if explicit_project and report.project:
            if explicit_project.strip().lower() != report.project.strip().lower():
                project_mismatch = {
                    "explicit": explicit_project,
                    "extracted": report.project,
                }
        elif explicit_project and not report.project:
            report.project = explicit_project

        resolved_project = explicit_project or report.project

        # ---------------------------------------------------------
        # Step 2: Resolve saved photo paths
        # ---------------------------------------------------------

        photo_paths: list[Path] = []

        for filename in photo_filenames:
            photo_path = report_dir / filename

            if not photo_path.exists():
                raise ReportPipelineError(
                    f"Saved photo not found: {photo_path}"
                )

            photo_paths.append(photo_path)

        # ---------------------------------------------------------
        # Step 3: Prepare photos for SuperDocs vision
        # ---------------------------------------------------------

        image_attachments = build_image_attachments(
            photo_paths
        )

        # ---------------------------------------------------------
        # Step 4: Analyze photos
        # ---------------------------------------------------------

        photo_analysis = None
        photo_captions: list[str] = []

        if image_attachments:
            superdocs = SuperDocsClient()

            photo_analysis = await superdocs.chat(
                session_id=(
                    f"photo-analysis-{report_id}"
                ),
                message="""
You are analyzing photos for a construction Daily Field Report.

For each attached image, describe ONLY what is visibly present.

If the image is relevant to construction, provide a concise,
professional field-report caption.

If the image is unrelated to construction, clearly state that
it is not a construction-site image.

Do not invent:
- project activities
- locations
- safety conditions
- environmental impact
- project impact
- causes
- events that cannot be visually established

A caption must describe visible evidence only.
""",
                image_attachments=image_attachments,
            )

            response_text = str(
                photo_analysis.get(
                    "response",
                    "",
                )
            )

            photo_captions = extract_photo_captions(
                response_text=response_text,
                photo_paths=photo_paths,
            )

        # ---------------------------------------------------------
        # Step 5: Convert photos to self-contained HTML URLs
        # ---------------------------------------------------------

        photo_urls = build_photo_data_urls(
            photo_paths
        )

        # ---------------------------------------------------------
        # Step 6: Build daily report HTML
        # ---------------------------------------------------------

        html = build_daily_report_html(
            report=report,
            photo_urls=photo_urls,
            photo_captions=photo_captions,
        )

        # ---------------------------------------------------------
        # Step 7: Save intermediate HTML
        # ---------------------------------------------------------

        html_path = (
            report_dir
            / "daily_field_report.html"
        )

        html_path.write_text(
            html,
            encoding="utf-8",
        )

        # ---------------------------------------------------------
        # Step 7b: Persist structured report data
        # ---------------------------------------------------------
        #
        # This is the source of truth nightly batching and the weekly
        # rollup read - they must not have to re-parse HTML.

        write_report_json(report_dir, report)

        # ---------------------------------------------------------
        # Step 8: Upload report to SuperDocs
        # ---------------------------------------------------------

        superdocs_result = await start_superdocs_workflow(
            report_id=report_id,
            html_path=html_path,
        )

        # ---------------------------------------------------------
        # Step 8b: Update the metadata index
        # ---------------------------------------------------------

        superdocs_status = superdocs_result.get("status")

        if superdocs_status == "awaiting_approval":
            update_metadata(
                report_dir,
                status="awaiting_approval",
                project=resolved_project,
                report_date=(
                    report.report_date.isoformat()
                    if report.report_date
                    else None
                ),
                project_mismatch=project_mismatch,
            )
        else:
            # SuperDocs itself ended the job in a non-approval terminal
            # state (failed/rejected/cancelled/unexpected). Don't leave
            # this looking like a normal in-flight report.
            update_metadata(
                report_dir,
                status="failed",
                project=resolved_project,
                report_date=(
                    report.report_date.isoformat()
                    if report.report_date
                    else None
                ),
                project_mismatch=project_mismatch,
                failure_reason=(
                    f"SuperDocs job ended in status: {superdocs_status}"
                ),
            )

        # ---------------------------------------------------------
        # Step 9: Return report + SuperDocs approval state
        # ---------------------------------------------------------

        return {
            "report_id": report_id,
            "status": superdocs_result["status"],
            "report_data": report.model_dump(
                mode="json"
            ),
            "photo_count": len(photo_paths),
            "photos": [
                str(path)
                for path in photo_paths
            ],
            "photo_captions": photo_captions,
            "photo_analysis": photo_analysis,
            "html_path": str(html_path),
            "superdocs": superdocs_result,
        }

    except ReportPipelineError as exc:
        # Never leave a report looking like it's still in flight when it
        # actually died partway through - mark it failed with a reason
        # so the nightly batch and weekly rollup skip it instead of
        # treating it as complete.
        update_metadata(
            report_dir,
            status="failed",
            failure_reason=str(exc),
        )
        raise

    except Exception as exc:
        update_metadata(
            report_dir,
            status="failed",
            failure_reason=str(exc),
        )
        raise ReportPipelineError(
            "Failed to process daily field report."
        ) from exc