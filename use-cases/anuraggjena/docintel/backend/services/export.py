import json
from typing import Optional
from uuid import UUID

from backend.repositories.export import ExportRepository
from backend.repositories.review import ReviewRepository, ClaimRepository
from backend.repositories.workspace import WorkspaceRepository
from backend.repositories.document import DocumentRepository
from backend.repositories.workflow import WorkflowRunRepository, WorkflowStageRepository
from backend.models.export import Export
from backend.core.export.docx_generator import DOCXGenerator
from backend.core.export.pdf_generator import PDFGenerator
from backend.storage.backend import StorageBackend
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ExportService:
    """Service for generating and managing exports"""

    def __init__(
        self,
        export_repository: ExportRepository,
        review_repository: ReviewRepository,
        claim_repository: ClaimRepository,
        workspace_repository: WorkspaceRepository,
        document_repository: DocumentRepository,
        run_repository: WorkflowRunRepository,
        stage_repository: WorkflowStageRepository,
        storage: StorageBackend,
        memo_section_repository=None,
    ):
        self.export_repository = export_repository
        self.review_repository = review_repository
        self.claim_repository = claim_repository
        self.workspace_repository = workspace_repository
        self.document_repository = document_repository
        self.run_repository = run_repository
        self.stage_repository = stage_repository
        self.storage = storage
        self.memo_section_repository = memo_section_repository

    async def export_review_as_docx(
        self,
        review_id: UUID,
        exported_by: Optional[str] = None,
    ) -> Export:
        """Export review as DOCX document."""
        logger.info("exporting_review_as_docx", review_id=str(review_id))

        review = await self.review_repository.get_by_id(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")

        workspace = await self.workspace_repository.get_by_id(UUID(str(review.workspace_id)))
        if not workspace:
            raise ValueError(f"Workspace {review.workspace_id} not found")

        claims = await self.claim_repository.list_by_review(review_id)

        # Retrieve actual generated report from workflow stage checkpoint
        generated_report = await self._get_generated_report(UUID(str(review.workflow_run_id)))

        # Get document name
        document_name = "Document"
        run = await self.run_repository.get_by_id(UUID(str(review.workflow_run_id)))
        if run:
            stages = await self.stage_repository.list_by_run(run.id)
            for stage in stages:
                if stage.checkpoint_data:
                    try:
                        data = stage.checkpoint_data
                        if isinstance(data, str):
                            data = json.loads(data)
                        doc_id = data.get("document_id")
                        if doc_id:
                            doc = await self.document_repository.get_by_id(UUID(doc_id))
                            if doc:
                                document_name = doc.filename
                                break
                    except Exception:
                        pass

        generator = DOCXGenerator()
        docx_bytes = generator.generate_tariff_report(
            workspace_name=workspace.name,
            document_name=document_name,
            claims=[{
                "content": claim.content,
                "status": claim.status,
            } for claim in claims],
            generated_report=generated_report,
        )

        filename = f"tariff_report_{review_id}.docx"
        storage_path = self.storage.save(docx_bytes, filename, str(review.workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(review.workspace_id),
            workflow_run_id=str(review.workflow_run_id),
            review_id=str(review_id),
            filename=filename,
            format="docx",
            storage_path=storage_path,
            file_size=len(docx_bytes),
            exported_by=exported_by,
        )

        logger.info("review_exported", export_id=str(export.id), size=len(docx_bytes))
        return export

    async def export_review_as_pdf(
        self,
        review_id: UUID,
        exported_by: Optional[str] = None,
    ) -> Export:
        """Export review as PDF document."""
        logger.info("exporting_review_as_pdf", review_id=str(review_id))

        review = await self.review_repository.get_by_id(review_id)
        if not review:
            raise ValueError(f"Review {review_id} not found")

        workspace = await self.workspace_repository.get_by_id(UUID(str(review.workspace_id)))
        if not workspace:
            raise ValueError(f"Workspace {review.workspace_id} not found")

        claims = await self.claim_repository.list_by_review(review_id)
        generated_report = await self._get_generated_report(UUID(str(review.workflow_run_id)))

        document_name = "Document"
        run = await self.run_repository.get_by_id(UUID(str(review.workflow_run_id)))
        if run:
            stages = await self.stage_repository.list_by_run(run.id)
            for stage in stages:
                if stage.checkpoint_data:
                    try:
                        data = stage.checkpoint_data
                        if isinstance(data, str):
                            data = json.loads(data)
                        doc_id = data.get("document_id")
                        if doc_id:
                            doc = await self.document_repository.get_by_id(UUID(doc_id))
                            if doc:
                                document_name = doc.filename
                                break
                    except Exception:
                        pass

        generator = PDFGenerator()
        pdf_bytes = generator.generate_tariff_report(
            workspace_name=workspace.name,
            document_name=document_name,
            claims=[{
                "content": claim.content,
                "status": claim.status,
            } for claim in claims],
            generated_report=generated_report,
        )

        filename = f"tariff_report_{review_id}.pdf"
        storage_path = self.storage.save(pdf_bytes, filename, str(review.workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(review.workspace_id),
            workflow_run_id=str(review.workflow_run_id),
            review_id=str(review_id),
            filename=filename,
            format="pdf",
            storage_path=storage_path,
            file_size=len(pdf_bytes),
            exported_by=exported_by,
        )

        logger.info("review_pdf_exported", export_id=str(export.id), size=len(pdf_bytes))
        return export

    async def export_run_as_docx(
        self,
        run_id: UUID,
        workspace_id: UUID,
        exported_by: Optional[str] = None,
        document_ids: Optional[list] = None,
    ) -> Export:
        """
        Export a completed workflow run as canonical Tariff memo DOCX.

        Requires MemoSection records to exist. Does NOT fall back to legacy export.

        Args:
            run_id: Workflow run ID
            workspace_id: Workspace ID
            exported_by: Optional user identifier
            document_ids: Optional list of document IDs for metadata resolution

        Returns:
            Export record

        Raises:
            ValueError: If run not found, not completed, or no MemoSections exist
        """
        logger.info("exporting_run_as_docx", run_id=str(run_id))

        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status not in ("completed", "running"):
            raise ValueError(f"Run {run_id} is not in exportable state (status: {run.status})")

        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        # REQUIRE MemoSectionRepository
        if not self.memo_section_repository:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "MemoSection repository not available"
            )

        # Load MemoSections
        sections = await self.memo_section_repository.list_by_run(run_id)

        # REQUIRE at least one section
        if not sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "no MemoSections exist for this run"
            )

        # Filter out skipped sections and validate we have content
        active_sections = [s for s in sections if s.status != "skipped"]

        if not active_sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"all {len(sections)} MemoSection(s) are marked as skipped"
            )

        # Check for at least one section with actual content
        has_content = any(
            s.content and s.content.strip()
            for s in active_sections
        )

        if not has_content:
            logger.warning(
                "export_memo_sections_empty",
                run_id=str(run_id),
                section_count=len(active_sections),
            )
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"{len(active_sections)} MemoSection(s) exist but all have empty content"
            )

        logger.info(
            "exporting_canonical_memo",
            run_id=str(run_id),
            total_sections=len(sections),
            active_sections=len(active_sections),
        )

    async def _resolve_tariff_export_metadata(
        self,
        run_id: UUID,
        workspace_id: UUID,
        document_ids: Optional[list] = None,
    ) -> tuple[dict, list, str, str]:
        """
        Resolve document metadata, product images, primary document name, and filename stem.

        Returns:
            (document_metadata, image_payloads, primary_doc_name, filename_stem)
        """
        import re
        from pathlib import Path

        document_metadata = {}
        image_payloads = []
        workspace_docs = []

        if self.document_repository:
            try:
                workspace_docs = await self.document_repository.list_by_workspace(workspace_id)
            except Exception as e:
                logger.warning(
                    "list_workspace_docs_failed",
                    workspace_id=str(workspace_id),
                    error=str(e),
                )

            for doc in workspace_docs:
                document_metadata[str(doc.id)] = {
                    "filename": doc.filename,
                    "document_role": doc.document_role,
                }
                if doc.document_role == "product_image" and doc.storage_path:
                    try:
                        image_bytes = self.storage.read(doc.storage_path)
                        image_payloads.append({
                            "bytes": image_bytes,
                            "filename": doc.filename,
                        })
                        logger.info(
                            "product_image_loaded",
                            filename=doc.filename,
                            size=len(image_bytes),
                        )
                    except Exception as img_error:
                        logger.warning(
                            "product_image_load_failed",
                            filename=doc.filename,
                            storage_path=doc.storage_path,
                            error=str(img_error),
                        )
                        image_payloads.append({
                            "bytes": None,
                            "filename": doc.filename,
                        })

            # Also ensure any explicitly passed document_ids are loaded if not already in document_metadata
            if document_ids:
                for doc_id in document_ids:
                    doc_id_str = str(doc_id)
                    if doc_id_str not in document_metadata:
                        try:
                            doc = await self.document_repository.get_by_id(UUID(doc_id_str))
                            if doc:
                                document_metadata[str(doc.id)] = {
                                    "filename": doc.filename,
                                    "document_role": doc.document_role,
                                }
                                if doc.document_role == "product_image" and doc.storage_path:
                                    try:
                                        image_bytes = self.storage.read(doc.storage_path)
                                        image_payloads.append({
                                            "bytes": image_bytes,
                                            "filename": doc.filename,
                                        })
                                    except Exception:
                                        pass
                        except Exception:
                            pass

        # Identify primary document
        primary_doc = None
        for doc in workspace_docs:
            if doc.document_role in ("product_spec", "primary", "product"):
                primary_doc = doc
                break
        if not primary_doc:
            for doc in workspace_docs:
                if doc.document_role != "product_image":
                    primary_doc = doc
                    break
        if not primary_doc and workspace_docs:
            primary_doc = workspace_docs[0]

        if primary_doc and primary_doc.filename:
            primary_doc_name = primary_doc.filename
            stem = Path(primary_doc.filename).stem
            clean_stem = re.sub(r'[^\w\-]+', '_', stem).strip('_')
            filename_stem = f"{clean_stem}_Tariff_Classification" if clean_stem else f"tariff_memo_run_{run_id}"
        else:
            primary_doc_name = "Workflow Output"
            filename_stem = f"tariff_memo_run_{run_id}"

        return document_metadata, image_payloads, primary_doc_name, filename_stem

    async def export_run_as_docx(
        self,
        run_id: UUID,
        workspace_id: UUID,
        exported_by: Optional[str] = None,
        document_ids: Optional[list] = None,
    ) -> Export:
        """
        Export a completed workflow run as canonical Tariff memo DOCX.

        Requires MemoSection records to exist. Does NOT fall back to legacy export.

        Args:
            run_id: Workflow run ID
            workspace_id: Workspace ID
            exported_by: Optional user identifier
            document_ids: Optional list of document IDs for metadata resolution

        Returns:
            Export record

        Raises:
            ValueError: If run not found, not completed, or no MemoSections exist
        """
        logger.info("exporting_run_as_docx", run_id=str(run_id))

        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status not in ("completed", "running"):
            raise ValueError(f"Run {run_id} is not in exportable state (status: {run.status})")

        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        # REQUIRE MemoSectionRepository
        if not self.memo_section_repository:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "MemoSection repository not available"
            )

        # Load MemoSections
        sections = await self.memo_section_repository.list_by_run(run_id)

        # REQUIRE at least one section
        if not sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "no MemoSections exist for this run"
            )

        # Filter out skipped sections and validate we have content
        active_sections = [s for s in sections if s.status != "skipped"]

        if not active_sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"all {len(sections)} MemoSection(s) are marked as skipped"
            )

        # Check for at least one section with actual content
        has_content = any(
            s.content and s.content.strip()
            for s in active_sections
        )

        if not has_content:
            logger.warning(
                "export_memo_sections_empty",
                run_id=str(run_id),
                section_count=len(active_sections),
            )
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"{len(active_sections)} MemoSection(s) exist but all have empty content"
            )

        logger.info(
            "exporting_canonical_memo",
            run_id=str(run_id),
            total_sections=len(sections),
            active_sections=len(active_sections),
        )

        (
            document_metadata,
            image_payloads,
            primary_doc_name,
            filename_stem,
        ) = await self._resolve_tariff_export_metadata(
            run_id=run_id,
            workspace_id=workspace_id,
            document_ids=document_ids,
        )

        # Build section payloads with enhanced source attribution
        section_payloads = []
        for s in active_sections:
            # Enhance source attribution with document metadata
            enhanced_attribution = []
            for attr in (s.source_attribution or []):
                enhanced_attr = dict(attr)
                doc_id = attr.get("document_id")
                if doc_id and doc_id in document_metadata:
                    enhanced_attr["document_name"] = document_metadata[doc_id]["filename"]
                enhanced_attribution.append(enhanced_attr)

            section_payloads.append({
                "title": s.title,
                "section_order": s.section_order,
                "content": s.content,
                "analyst_reasoning": s.analyst_reasoning,
                "source_attribution": enhanced_attribution,
                "structured_data": s.structured_data,
                "status": s.status,
            })

        generator = DOCXGenerator()
        docx_bytes = generator.generate_tariff_memo(
            workspace_name=workspace.name,
            document_name=primary_doc_name,
            sections=section_payloads,
            images=image_payloads if image_payloads else None,
        )

        filename = f"{filename_stem}.docx"
        storage_path = self.storage.save(docx_bytes, filename, str(workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(workspace_id),
            workflow_run_id=str(run_id),
            review_id=None,
            filename=filename,
            format="docx",
            storage_path=storage_path,
            file_size=len(docx_bytes),
            exported_by=exported_by,
        )

        logger.info(
            "canonical_memo_exported",
            export_id=str(export.id),
            sections=len(active_sections),
        )
        return export

    async def export_run_as_pdf(
        self,
        run_id: UUID,
        workspace_id: UUID,
        exported_by: Optional[str] = None,
        document_ids: Optional[list] = None,
    ) -> Export:
        """
        Export a completed workflow run as canonical Tariff memo PDF.

        Requires MemoSection records to exist. Does NOT fall back to legacy export.
        """
        logger.info("exporting_run_as_pdf", run_id=str(run_id))

        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        if run.status not in ("completed", "running"):
            raise ValueError(f"Run {run_id} is not in exportable state (status: {run.status})")

        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        if not self.memo_section_repository:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "MemoSection repository not available"
            )

        sections = await self.memo_section_repository.list_by_run(run_id)

        if not sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                "no MemoSections exist for this run"
            )

        active_sections = [s for s in sections if s.status != "skipped"]

        if not active_sections:
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"all {len(sections)} MemoSection(s) are marked as skipped"
            )

        has_content = any(
            s.content and s.content.strip()
            for s in active_sections
        )

        if not has_content:
            logger.warning(
                "export_memo_sections_empty",
                run_id=str(run_id),
                section_count=len(active_sections),
            )
            raise ValueError(
                f"Cannot export Tariff memo for run {run_id}: "
                f"{len(active_sections)} MemoSection(s) exist but all have empty content"
            )

        logger.info(
            "exporting_canonical_memo_pdf",
            run_id=str(run_id),
            total_sections=len(sections),
            active_sections=len(active_sections),
        )

        (
            document_metadata,
            image_payloads,
            primary_doc_name,
            filename_stem,
        ) = await self._resolve_tariff_export_metadata(
            run_id=run_id,
            workspace_id=workspace_id,
            document_ids=document_ids,
        )

        section_payloads = []
        for s in active_sections:
            enhanced_attribution = []
            for attr in (s.source_attribution or []):
                enhanced_attr = dict(attr)
                doc_id = attr.get("document_id")
                if doc_id and doc_id in document_metadata:
                    enhanced_attr["document_name"] = document_metadata[doc_id]["filename"]
                enhanced_attribution.append(enhanced_attr)

            section_payloads.append({
                "title": s.title,
                "section_order": s.section_order,
                "content": s.content,
                "analyst_reasoning": s.analyst_reasoning,
                "source_attribution": enhanced_attribution,
                "structured_data": s.structured_data,
                "status": s.status,
            })

        generator = PDFGenerator()
        pdf_bytes = generator.generate_tariff_memo(
            workspace_name=workspace.name,
            document_name=primary_doc_name,
            sections=section_payloads,
            images=image_payloads if image_payloads else None,
        )

        filename = f"{filename_stem}.pdf"
        storage_path = self.storage.save(pdf_bytes, filename, str(workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(workspace_id),
            workflow_run_id=str(run_id),
            review_id=None,
            filename=filename,
            format="pdf",
            storage_path=storage_path,
            file_size=len(pdf_bytes),
            exported_by=exported_by,
        )

        logger.info(
            "canonical_memo_pdf_exported",
            export_id=str(export.id),
            sections=len(active_sections),
        )
        return export


    async def _get_generated_report(self, run_id: UUID) -> str:
        """
        Retrieve the generated report text from the workflow stage checkpoint data.

        Falls back to empty string if not found.
        """
        try:
            stages = await self.stage_repository.list_by_run(run_id)
            for stage in reversed(stages):
                if stage.stage_name == "generate" and stage.status == "completed":
                    data = stage.checkpoint_data
                    if data:
                        if isinstance(data, str):
                            data = json.loads(data)
                        report = data.get("generated_report")
                        if report:
                            logger.info("generated_report_retrieved", run_id=str(run_id), length=len(report))
                            return report
        except Exception as e:
            logger.warning("generated_report_retrieval_failed", run_id=str(run_id), error=str(e))

        logger.warning("generated_report_not_found", run_id=str(run_id))
        return ""

    async def get_export(self, export_id: UUID) -> Optional[Export]:
        return await self.export_repository.get_by_id(export_id)

    async def get_export_content(self, export_id: UUID) -> Optional[bytes]:
        export = await self.export_repository.get_by_id(export_id)
        if not export:
            return None
        try:
            return self.storage.read(export.storage_path)
        except Exception as e:
            logger.error("export_read_failed", error=str(e), export_id=str(export_id))
            return None

    async def list_workspace_exports(self, workspace_id: UUID):
        return await self.export_repository.list_by_workspace(workspace_id)

    async def export_screenplay_as_docx(
        self,
        run_id: UUID,
        workspace_id: UUID,
        exported_by: Optional[str] = None,
        formatting_items: Optional[list] = None,
    ) -> Export:
        """Export a completed screenplay run as formatted DOCX."""
        logger.info("exporting_screenplay_as_docx", run_id=str(run_id))

        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        # Prefer explicitly supplied items (fetched from the FormattingItem table by
        # the caller, which owns the DB session); otherwise fall back to the diff
        # stage checkpoint data.
        items = formatting_items
        if items is None:
            items = await self._get_screenplay_items(run_id)

        generator = DOCXGenerator()
        docx_bytes = generator.generate_screenplay_docx(
            formatting_items=items,
            title="Formatted Screenplay",
            workspace_name=workspace.name,
        )

        filename = f"screenplay_{run_id}.docx"
        storage_path = self.storage.save(docx_bytes, filename, str(workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(workspace_id),
            workflow_run_id=str(run_id),
            review_id=None,
            filename=filename,
            format="screenplay_docx",
            storage_path=storage_path,
            file_size=len(docx_bytes),
            exported_by=exported_by,
        )
        logger.info("screenplay_exported", export_id=str(export.id))
        return export

    async def export_screenplay_as_pdf(
        self,
        run_id: UUID,
        workspace_id: UUID,
        exported_by: Optional[str] = None,
        formatting_items: Optional[list] = None,
    ) -> Export:
        """Export a completed screenplay run as formatted PDF."""
        logger.info("exporting_screenplay_as_pdf", run_id=str(run_id))

        run = await self.run_repository.get_by_id(run_id)
        if not run:
            raise ValueError(f"Run {run_id} not found")

        workspace = await self.workspace_repository.get_by_id(workspace_id)
        if not workspace:
            raise ValueError(f"Workspace {workspace_id} not found")

        items = formatting_items
        if items is None:
            items = await self._get_screenplay_items(run_id)

        generator = PDFGenerator()
        pdf_bytes = generator.generate_screenplay_pdf(
            formatting_items=items,
            title="Formatted Screenplay",
            workspace_name=workspace.name,
        )

        filename = f"screenplay_{run_id}.pdf"
        storage_path = self.storage.save(pdf_bytes, filename, str(workspace_id))

        export = await self.export_repository.create(
            workspace_id=str(workspace_id),
            workflow_run_id=str(run_id),
            review_id=None,
            filename=filename,
            format="screenplay_pdf",
            storage_path=storage_path,
            file_size=len(pdf_bytes),
            exported_by=exported_by,
        )
        logger.info("screenplay_pdf_exported", export_id=str(export.id))
        return export


    async def _get_screenplay_items(self, run_id: UUID) -> list:
        """Retrieve FormattingItems from stage checkpoint data."""
        try:
            stages = await self.stage_repository.list_by_run(run_id)
            for stage in reversed(stages):
                if stage.stage_name == "diff" and stage.status == "completed":
                    data = stage.checkpoint_data
                    if data:
                        if isinstance(data, str):
                            data = json.loads(data)
                        items = data.get("formatting_items", [])
                        if items:
                            return items
        except Exception as e:
            logger.warning("screenplay_items_retrieval_failed", run_id=str(run_id), error=str(e))
        return []
