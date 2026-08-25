"""Close pack generation.

The old implementation looped over six stage strings with `asyncio.sleep(0.05)` and
produced nothing at all: no SuperDocs call, no documents, no review items. Reviews were
instead seeded into the fixture, so a reviewer could approve changes before generation
had ever run.

This version does the real work and records honest failures.
"""

import asyncio
import logging
from typing import Any

from ..db import store
from ..integrations.superdocs.client import EDIT, UPLOAD, SuperDocsResponseError, get_client
from . import storage, superdocs_ops
from .clock import now_iso
from .closes import audit, clear_generation, invalidate_export, new_id
from .memo import upsert_supporting_memo
from .readiness import calculate_readiness

logger = logging.getLogger(__name__)

STAGES: list[tuple[str, str]] = [
    ("CHECKING", "Checking required documents"),
    ("PREPARING", "Preparing sources"),
    ("UPLOADING", "Uploading to SuperDocs"),
    ("GENERATING", "Generating close documents"),
    ("REVIEW", "Preparing review"),
]

STAGE_LABELS = [label for _, label in STAGES]

INSTRUCTION = (
    "Draft the month-end close pack narrative from the attached source documents. "
    "Revise each section below in place so it reflects the evidence in the uploaded "
    "documents, citing the source document for each proposed change."
)


def working_narrative(close: dict[str, Any]) -> str:
    """The document the edit actually operates on: a close pack narrative to revise.

    The working document used to be whichever source file happened to be uploaded first
    - normally the trial balance. The instruction asks for revisions to the revenue
    summary, accrual exceptions and checklist footnotes, and a trial balance contains no
    such sections, so the model correctly proposed nothing and generation failed with
    "proposed no changes".

    A narrative skeleton gives the edit real sections to work on. The source documents are
    already loaded into the same session by the uploads above, so they remain the evidence
    the model draws on; this is the thing being drafted, not a replacement for them.
    """
    entity = close.get("entity", "the entity")
    period = close.get("period", "")
    rows = "\n".join(
        f"<p>{section}: to be drafted from the uploaded source documents.</p>"
        for section in (
            "Revenue summary",
            "Accrual exceptions",
            "Checklist footnotes",
            "Balance sheet movements",
            "Management commentary",
        )
    )
    return f"<h1>Close Pack Narrative - {entity} - {period}</h1>\n{rows}"


def new_job(close_id: str, actor_name: str) -> dict[str, Any]:
    return {
        "id": new_id("job"),
        "close_id": close_id,
        "status": "RUNNING",
        "stage": STAGES[0][0],
        "stage_index": 0,
        "stages": STAGE_LABELS,
        "attempt": 1,
        "error": None,
        "started_by": actor_name,
        "started_at": now_iso(),
        "completed_at": None,
    }


async def _set_stage(job: dict[str, Any], index: int) -> None:
    job["stage_index"] = index
    job["stage"] = STAGES[index][0]
    await asyncio.to_thread(store.save_job, job)


async def run_generation(job_id: str, close_id: str, actor: dict[str, Any]) -> None:
    job = await asyncio.to_thread(store.get_job, job_id)
    if job is None:
        logger.error("Generation job %s vanished before it started", job_id)
        return

    try:
        await _set_stage(job, 0)
        close = await asyncio.to_thread(store.get_close, close_id)
        if close is None:
            raise SuperDocsResponseError(f"Close {close_id} no longer exists")

        ready_documents = [doc for doc in close["documents"] if doc["status"] == "READY"]
        if not ready_documents:
            raise SuperDocsResponseError("No classified documents are available to generate from")

        await _set_stage(job, 1)
        payloads: list[tuple[str, bytes]] = []
        for document in ready_documents:
            content = await asyncio.to_thread(storage.get_bytes, document["storage_key"])
            payloads.append((document["filename"], content))

        await _set_stage(job, 2)
        client = get_client()
        uploaded_ids: list[str] = []
        for filename, content in payloads:
            result, _ = await superdocs_ops.call(
                close_id,
                UPLOAD,
                lambda filename=filename, content=content: client.upload_document(filename, content),
                detail=filename,
            )
            document_id = result.get("document_id")
            if not document_id:
                raise SuperDocsResponseError(f"SuperDocs upload of {filename!r} returned no document_id")
            uploaded_ids.append(document_id)

        await _set_stage(job, 3)
        working_document_id = uploaded_ids[0]
        narrative = working_narrative(close)
        changes, _ = await superdocs_ops.call(
            close_id,
            EDIT,
            lambda: client.edit_document(working_document_id, INSTRUCTION, narrative),
            document_id=working_document_id,
            detail=f"{len(uploaded_ids)} source documents",
        )

        await _set_stage(job, 4)

        def apply(close: dict[str, Any]) -> None:
            clear_generation(close)
            close["superdocs_document_ids"] = uploaded_ids
            close["superdocs_working_document_id"] = working_document_id
            # A new edit round invalidates the previous SuperDocs export too.
            close["superdocs_export"] = None
            # Regenerating replaces only undecided items; decisions already made stand.
            decided = [item for item in close["reviews"] if item["status"] != "PENDING"]
            decided_keys = {item.get("external_change_id") for item in decided}
            fresh = [
                {
                    "id": new_id("rev"),
                    "external_change_id": change.get("external_change_id"),
                    "section": change["section"],
                    "before_value": change["before_value"],
                    "after_value": change["after_value"],
                    "source_reference": change.get("source_reference", ""),
                    "status": "PENDING",
                    "reviewed_by": None,
                    "reviewed_at": None,
                    "reason": None,
                }
                for change in changes
                if change.get("external_change_id") not in decided_keys
            ]
            close["reviews"] = decided + fresh
            # The memo is a generated artifact, not an export-time assembly step: it has
            # to exist in the UI as soon as generation finishes.
            memo = upsert_supporting_memo(close, calculate_readiness(close))
            audit(
                close,
                "GENERATION_COMPLETED",
                actor,
                f"{len(uploaded_ids)} source documents processed, {len(fresh)} changes proposed",
            )
            audit(close, "ARTIFACT_GENERATED", actor, f"{memo['name']} ({memo['size']} bytes)")
            # Regenerating rewrites the review queue, so any pack exported before now
            # describes a close that no longer exists.
            invalidate_export(close, actor)

        await asyncio.to_thread(store.mutate_close, close_id, apply)

        job.update({"status": "SUCCEEDED", "stage": "COMPLETE", "stage_index": len(STAGES), "completed_at": now_iso()})
        await asyncio.to_thread(store.save_job, job)

    except Exception as exc:  # noqa: BLE001 - surfaced to the client via job.error
        logger.exception("Generation job %s failed", job_id)
        message = str(exc) or exc.__class__.__name__
        job.update({"status": "FAILED", "error": message, "completed_at": now_iso()})
        await asyncio.to_thread(store.save_job, job)

        def mark_failed(close: dict[str, Any]) -> None:
            clear_generation(close)
            audit(close, "GENERATION_FAILED", actor, message)

        try:
            await asyncio.to_thread(store.mutate_close, close_id, mark_failed)
        except KeyError:
            logger.error("Could not record generation failure: close %s is gone", close_id)
    finally:
        await asyncio.to_thread(store.prune_jobs)
