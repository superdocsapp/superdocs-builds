from typing import List, Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.workflow import WorkflowRepository, WorkflowRunRepository, WorkflowStageRepository
from backend.repositories.document import DocumentRepository
from backend.models.workflow import WorkflowRun
from backend.storage.backend import StorageBackend
from backend.logging_config import get_logger

logger = get_logger(__name__)


class WorkflowService:
    """Service for creating and managing workflow runs."""

    def __init__(
        self,
        workflow_repository: WorkflowRepository,
        run_repository: WorkflowRunRepository,
        stage_repository: WorkflowStageRepository,
        document_repository: DocumentRepository,
        storage: StorageBackend,
    ):
        self.workflow_repository = workflow_repository
        self.run_repository = run_repository
        self.stage_repository = stage_repository
        self.document_repository = document_repository
        self.storage = storage

    async def create_run(
        self,
        workspace_id: UUID,
        workflow_slug: str,
        document_id: UUID,
        created_by: str = "system",
    ) -> WorkflowRun:
        """
        Create a workflow run record and enqueue it.

        Returns the created WorkflowRun. Does NOT start execution — the caller
        is responsible for handing off to the TaskManager.
        """
        # Resolve workflow DB record by slug
        workflow = await self.workflow_repository.get_by_slug(workflow_slug)
        if not workflow:
            raise ValueError(f"Workflow '{workflow_slug}' not found")

        # Check document exists
        document = await self.document_repository.get_by_id(document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Check for an already-active run on the same workspace+workflow
        existing_runs = await self.run_repository.list_by_workspace(workspace_id)
        for run in existing_runs:
            if run.workflow_id == workflow.id and run.status in ("queued", "running"):
                logger.info(
                    "workflow_run_already_active",
                    run_id=str(run.id),
                    status=run.status,
                )
                return run

        run = await self.run_repository.create(
            workspace_id=workspace_id,
            workflow_id=workflow.id,
            status="queued",
            workflow_version=workflow.current_version,
            created_by=created_by,
            version_number=1,
        )

        logger.info(
            "workflow_run_created",
            run_id=str(run.id),
            workflow=workflow_slug,
            document_id=str(document_id),
        )
        return run

    async def build_initial_state(self, run_id: UUID, document_id: UUID) -> dict:
        """
        Build the initial workflow state dict for TaskManager.

        Extracts document text content from storage so stages can use it.
        """
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        document = await self.document_repository.get_by_id(document_id)
        if not document:
            raise ValueError(f"Document {document_id} not found")

        # Extract text content from stored file
        document_content = await self._extract_text(document)

        return {
            "workflow_run_id": str(run_id),
            "workspace_id": str(run.workspace_id),
            "document_id": str(document_id),
            "document_content": document_content,
            "document_text": document_content,
            "status": "queued",
        }

    async def _extract_text(self, document) -> str:
        """Extract plain text from a document file."""
        try:
            content_bytes = self.storage.read(document.storage_path)
        except Exception as e:
            logger.error("document_read_failed", path=document.storage_path, error=str(e))
            return ""

        mime = (document.mime_type or "").lower()

        if mime == "text/plain" or document.filename.endswith(".txt"):
            try:
                return content_bytes.decode("utf-8", errors="replace")
            except Exception:
                return content_bytes.decode("latin-1", errors="replace")

        if mime == "application/pdf" or document.filename.endswith(".pdf"):
            return _extract_pdf_text(content_bytes)

        if mime in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ) or document.filename.endswith(".docx"):
            return _extract_docx_text(content_bytes)

        # Fallback: try UTF-8 decode
        try:
            return content_bytes.decode("utf-8", errors="replace")
        except Exception:
            return ""

    async def get_run(self, run_id: UUID) -> Optional[WorkflowRun]:
        return await self.run_repository.get_by_id(run_id)

    async def list_workspace_runs(self, workspace_id: UUID) -> List[WorkflowRun]:
        return await self.run_repository.list_by_workspace(workspace_id)

    async def get_run_stages(self, run_id: UUID):
        return await self.stage_repository.list_by_run(run_id)

    async def resolve_run_document_id(self, run: WorkflowRun) -> Optional[UUID]:
        """Attempt to resolve the source document ID for a workflow run."""
        # 1. Check stages checkpoint data
        stages = await self.stage_repository.list_by_run(run.id)
        for stage in stages:
            if stage.checkpoint_data:
                try:
                    import json
                    data = json.loads(stage.checkpoint_data)
                    doc_id_str = data.get("document_id")
                    if doc_id_str:
                        return UUID(doc_id_str)
                except Exception:
                    pass

        # 2. Check Evidence table
        from backend.repositories.evidence import EvidenceRepository
        evidence_repo = EvidenceRepository(self.stage_repository.session)
        evidence_list = await evidence_repo.list_by_run(run.id)
        for ev in evidence_list:
            if ev.document_id:
                return ev.document_id

        # 3. Check documents in workspace
        docs = await self.document_repository.list_by_workspace(run.workspace_id)
        if docs:
            return docs[0].id

        return None

    async def replay_run(
        self,
        workspace_id: UUID,
        original_run_id: UUID,
        created_by: str = "system",
    ) -> tuple[WorkflowRun, UUID]:
        """
        Replay an existing workflow run by creating a new, independent run with the
        same workflow and input document, without modifying the original run.

        Returns (new_run, document_id).
        """
        original_run = await self.run_repository.get_by_id(original_run_id)
        if not original_run or original_run.workspace_id != workspace_id:
            raise ValueError(f"Original run {original_run_id} not found in workspace {workspace_id}")

        workflow = await self.workflow_repository.get_by_id(original_run.workflow_id)
        if not workflow:
            raise ValueError(f"Workflow {original_run.workflow_id} not found")

        document_id = await self.resolve_run_document_id(original_run)
        if not document_id:
            raise ValueError(f"Could not determine source document for run {original_run_id}")

        new_run = await self.create_run(
            workspace_id=workspace_id,
            workflow_slug=workflow.slug,
            document_id=document_id,
            created_by=created_by,
        )

        return new_run, document_id

    async def resume_run(self, run_id: UUID) -> bool:
        """Resume a waiting workflow run."""
        from backend.core.workflow.task_manager import get_task_manager
        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")
        workflow = await self.workflow_repository.get_by_id(run.workflow_id)
        workflow_name = workflow.slug if workflow else "tariff_classification"

        tm = get_task_manager()
        await tm.resume_workflow(run_id, workflow_name)
        return True

    async def is_run_resumable(self, run: WorkflowRun) -> bool:
        """
        Determine if a workflow run can be resumed.
        
        Returns False if the run is completed, running, or queued.
        Returns True if at least one stage completed (or skipped) with valid checkpoint data.
        """
        if run.status in ("completed", "queued", "running"):
            return False

        stages = await self.stage_repository.list_by_run(run.id)
        for stage in stages:
            if stage.status in ("completed", "skipped") and stage.checkpoint_data:
                try:
                    import json
                    data = json.loads(stage.checkpoint_data)
                    if isinstance(data, dict) and len(data) > 0:
                        return True
                except Exception:
                    continue
        return False

    async def cancel_run(self, run_id: UUID) -> bool:
        from backend.core.workflow.task_manager import get_task_manager
        try:
            tm = get_task_manager()
            await tm.cancel_workflow(run_id)
        except RuntimeError:
            pass

        # Ensure DB status is set to cancelled
        from datetime import datetime, timezone
        run = await self.run_repository.update(
            run_id,
            status="cancelled",
            completed_at=datetime.now(timezone.utc),
            current_stage=None
        )
        return run is not None



def _extract_pdf_text(content: bytes) -> str:
    try:
        import io
        try:
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(content))
            try:
                pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
            except Exception:
                pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(pages)
        except ImportError:
            pass

        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(content)) as pdf:
                pages = [page.extract_text() or "" for page in pdf.pages]
            return "\n\n".join(pages)
        except ImportError:
            pass

        return "[PDF text extraction unavailable — install pypdf or pdfplumber]"
    except Exception as e:
        logger.warning("pdf_extraction_failed", error=str(e))
        return ""


def _extract_docx_text(content: bytes) -> str:
    try:
        import io
        import docx
        doc = docx.Document(io.BytesIO(content))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    except Exception as e:
        logger.warning("docx_extraction_failed", error=str(e))
        return ""
