"""Application-level orchestration around the SuperDocs transport."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from typing import Any, Mapping

from .documents import manuscript_filename, render_manuscript_html
from .models import ManuscriptSkeleton
from .superdocs import (
    EditJob,
    ExportedDocument,
    JobSnapshot,
    SuperDocsPort,
    UploadedDocument,
)


class DecisionConflictError(ValueError):
    """A decided change cannot be submitted later with a different decision."""


@dataclass(frozen=True)
class DecisionResult:
    change_id: str
    approved: bool
    idempotent_replay: bool
    upstream_response: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "change_id": self.change_id,
            "approved": self.approved,
            "idempotent_replay": self.idempotent_replay,
            "upstream_response": dict(self.upstream_response),
        }


class SuperDocsWorkflowService:
    """Keep transport details out of the existing manuscript core."""

    def __init__(self, adapter: SuperDocsPort) -> None:
        self._adapter = adapter
        self._decision_lock = threading.Lock()
        self._decisions: dict[
            tuple[str, str, str], tuple[bool, str, Mapping[str, Any]]
        ] = {}

    def upload_scaffold(
        self,
        skeleton: ManuscriptSkeleton,
        generated_sections: Mapping[str, str],
    ) -> UploadedDocument:
        html = render_manuscript_html(skeleton, generated_sections)
        session_id = f"paper-{skeleton.manuscript_id}-{uuid.uuid4().hex[:12]}"
        return self._adapter.upload_document(
            filename=manuscript_filename(skeleton),
            content=html.encode("utf-8"),
            session_id=session_id,
        )

    def send_edit_instruction(
        self, *, session_id: str, instruction: str, document_html: str | None = None
    ) -> EditJob:
        return self._adapter.send_edit_instruction(
            session_id=session_id,
            document_html=document_html,
            instruction=instruction,
        )

    def get_job(self, *, job_id: str) -> JobSnapshot:
        return self._adapter.get_job(job_id=job_id)

    def decide_change(
        self,
        *,
        session_id: str,
        job_id: str,
        change_id: str,
        approved: bool,
        feedback: str = "",
    ) -> DecisionResult:
        key = (session_id, job_id, change_id)
        normalized_feedback = feedback.strip()
        with self._decision_lock:
            previous = self._decisions.get(key)
            if previous:
                old_approved, old_feedback, old_response = previous
                if (old_approved, old_feedback) != (approved, normalized_feedback):
                    raise DecisionConflictError(
                        "This change already has a different recorded decision."
                    )
                return DecisionResult(
                    change_id, approved, True, old_response
                )

            if approved:
                response = self._adapter.approve_change(
                    session_id=session_id,
                    job_id=job_id,
                    change_id=change_id,
                )
            else:
                response = self._adapter.reject_change(
                    session_id=session_id,
                    job_id=job_id,
                    change_id=change_id,
                    feedback=normalized_feedback,
                )
            self._decisions[key] = (approved, normalized_feedback, response)
            return DecisionResult(change_id, approved, False, response)

    def export_document(
        self, *, session_id: str, file_format: str, filename: str
    ) -> ExportedDocument:
        return self._adapter.export_document(
            session_id=session_id,
            file_format=file_format,
            filename=filename,
        )
