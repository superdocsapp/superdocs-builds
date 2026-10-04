"""Worker loop — processes jobs through the SuperDocs pipeline.

Phase 1 (prepare): download → upload → chat → REVIEW_PENDING (human gate)
Phase 2 (complete): approve → export → write-back → COMPLETED (after human approval)
"""
import json
import logging
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.job import Job, JobStatus
from app.models.folder_config import FolderConfig
from app.services.state_machine import (
    transition,
    claim_job,
    claim_approved_job,
    InvalidTransition,
)
from app.services.antiloop import register_output
from app.services.superdocs_client import (
    SuperDocsClientProtocol,
    PreviewModeBlocked,
    ProposedChange,
)
from app.services.dropbox_client import DropboxClientProtocol

logger = logging.getLogger(__name__)


def serialize_proposed_changes(changes: list[ProposedChange]) -> str:
    return json.dumps([{"content": c.content, "raw": c.raw} for c in changes])


def deserialize_proposed_changes(raw: Optional[str]) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


class WorkerLoop:
    """Processes jobs from QUEUED through review, then completes after approval."""

    def __init__(
        self,
        dropbox: DropboxClientProtocol,
        superdocs: SuperDocsClientProtocol,
        worker_id: str = "worker-1",
    ):
        self.dropbox = dropbox
        self.superdocs = superdocs
        self.worker_id = worker_id

    def prepare_job_for_review(self, db: Session, job: Job) -> Job:
        """Run upload + chat, then stop at REVIEW_PENDING for human review."""
        folder_config = db.query(FolderConfig).filter(
            FolderConfig.id == job.folder_config_id
        ).one()

        is_preview = job.preview

        try:
            if not job.superdocs_doc_id:
                logger.info(
                    "Job %s: Downloading %s (rev=%s)",
                    job.id, job.source_path, job.source_rev,
                )
                file_content = self.dropbox.download_file(
                    job.source_path, rev=job.source_rev,
                )
                filename = (
                    job.source_path.rsplit("/", 1)[-1]
                    if "/" in job.source_path else job.source_path
                )

                try:
                    upload_result = self.superdocs.upload_document(
                        file_content, filename, preview=is_preview,
                    )
                    job.superdocs_doc_id = upload_result.document_id
                except PreviewModeBlocked:
                    job.locked_by = None
                    job.locked_at = None
                    transition(
                        db, job, JobStatus.REVIEW_PENDING, actor=self.worker_id,
                        detail="PREVIEW MODE: upload blocked, zero spend",
                    )
                    db.commit()
                    return job

            instruction = (
                folder_config.instruction_text
                or f"Apply treatment: {folder_config.treatment}"
            )
            try:
                chat_result = self.superdocs.send_edit_instruction(
                    job.superdocs_doc_id, instruction, preview=is_preview,
                )
                job.proposed_changes_json = serialize_proposed_changes(
                    chat_result.proposed_changes,
                )
                logger.info(
                    "Job %s: %d proposed changes awaiting review",
                    job.id, len(chat_result.proposed_changes),
                )
            except PreviewModeBlocked:
                job.locked_by = None
                job.locked_at = None
                transition(
                    db, job, JobStatus.REVIEW_PENDING, actor=self.worker_id,
                    detail="PREVIEW MODE: chat blocked, zero spend",
                )
                db.commit()
                return job

            job.locked_by = None
            job.locked_at = None
            transition(
                db, job, JobStatus.REVIEW_PENDING, actor=self.worker_id,
                detail=(
                    f"{len(chat_result.proposed_changes)} changes "
                    "awaiting human review"
                ),
            )
            db.commit()
            logger.info("Job %s: REVIEW_PENDING — waiting for human gate", job.id)
            return job

        except PreviewModeBlocked:
            logger.info("Job %s: preview mode — no operations spent", job.id)
            db.commit()
            return job

        except InvalidTransition as e:
            logger.error("Job %s: STATE MACHINE BUG: %s", job.id, e)
            db.rollback()
            raise

        except Exception as e:
            return self._mark_failed(db, job, e)

    def complete_approved_job(self, db: Session, job: Job) -> Job:
        """After human approval: SuperDocs approve → export → Dropbox write-back."""
        folder_config = db.query(FolderConfig).filter(
            FolderConfig.id == job.folder_config_id
        ).one()

        if job.preview:
            transition(
                db, job, JobStatus.COMPLETED, actor=self.worker_id,
                detail="PREVIEW MODE: approved in review, no write-back",
            )
            db.commit()
            return job

        try:
            self.superdocs.approve_changes(job.superdocs_doc_id)
            transition(
                db, job, JobStatus.EXPORTING, actor=self.worker_id,
                detail="SuperDocs changes approved after human gate",
            )

            export_result = self.superdocs.export_document(job.superdocs_doc_id)

            transition(db, job, JobStatus.WRITING_BACK, actor=self.worker_id)
            output_path = _build_output_path(
                job.source_path,
                folder_config.output_naming_pattern,
                folder_config.treatment,
            )

            upload_meta = self.dropbox.upload_file(
                output_path, export_result.content, overwrite=True,
            )

            register_output(
                db, job.id, output_path,
                output_rev=upload_meta.rev,
                output_content_hash=upload_meta.content_hash,
            )

            transition(
                db, job, JobStatus.COMPLETED, actor=self.worker_id,
                detail=f"Output written to {output_path}",
            )
            db.commit()
            logger.info("Job %s: COMPLETED -> %s", job.id, output_path)
            return job

        except InvalidTransition as e:
            logger.error("Job %s: STATE MACHINE BUG: %s", job.id, e)
            db.rollback()
            raise

        except Exception as e:
            return self._mark_failed(db, job, e)

    def process_job(self, db: Session, job: Job) -> Job:
        """Prepare a PROCESSING job for human review."""
        return self.prepare_job_for_review(db, job)

    def process_next_queued(self, db: Session) -> Optional[Job]:
        queued_job = (
            db.query(Job)
            .filter(Job.status == JobStatus.QUEUED)
            .order_by(Job.created_at.asc())
            .first()
        )
        if queued_job is None:
            return None

        claimed = claim_job(db, queued_job.id, self.worker_id)
        if claimed is None:
            logger.debug("Job was claimed by another worker")
            return None

        db.commit()
        return self.prepare_job_for_review(db, claimed)

    def process_next_approved(self, db: Session) -> Optional[Job]:
        approved_job = (
            db.query(Job)
            .filter(Job.status == JobStatus.APPROVED)
            .order_by(Job.updated_at.asc())
            .first()
        )
        if approved_job is None:
            return None

        claimed = claim_approved_job(db, approved_job.id, self.worker_id)
        if claimed is None:
            return None

        db.commit()
        return self.complete_approved_job(db, claimed)

    def _mark_failed(self, db: Session, job: Job, error: Exception) -> Job:
        logger.error("Job %s: FAILED: %s", job.id, error, exc_info=True)
        job_id = job.id
        try:
            db.rollback()
            job = db.query(Job).filter(Job.id == job_id).one()
            transition(
                db, job, JobStatus.FAILED, actor=self.worker_id,
                detail=str(error)[:500],
            )
            job.retry_count += 1
            db.commit()
        except Exception as inner_e:
            logger.error("Job %s: Failed to record failure: %s", job_id, inner_e)
            db.rollback()
        return job


def _build_output_path(source_path: str, naming_pattern: str, treatment: str) -> str:
    if "/" in source_path:
        directory, filename = source_path.rsplit("/", 1)
    else:
        directory, filename = "", source_path

    if "." in filename:
        name_part, ext = filename.rsplit(".", 1)
        ext = "." + ext
    else:
        name_part, ext = filename, ""

    output_name = naming_pattern.format(
        basename=name_part,
        treatment=treatment,
        ext=ext,
    )

    if directory:
        return f"{directory}/{output_name}"
    return output_name
