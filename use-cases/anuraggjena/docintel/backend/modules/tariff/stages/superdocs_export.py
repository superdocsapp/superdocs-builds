"""Terminal export stage for tariff workflow."""

from typing import Dict, Any, List, Optional
from uuid import UUID

from backend.core.workflow.stage import StageNode
from backend.modules.tariff.schemas import TariffWorkflowState
from backend.logging_config import get_logger

logger = get_logger(__name__)


class SuperDocsExportStage(StageNode[TariffWorkflowState]):
    """Export approved canonical Tariff memo document after human review, then embed product images."""

    def __init__(
        self,
        export_service: Any,
        document_repository=None,
        storage_backend=None,
    ):
        super().__init__("superdocs_export")
        self._export_service = export_service
        self._document_repository = document_repository
        self._storage_backend = storage_backend

    async def execute(self, state: TariffWorkflowState) -> Dict[str, Any]:
        run_id = UUID(state.workflow_run_id)
        workspace_id = UUID(state.workspace_id)

        logger.info(
            "tariff_export_stage_starting",
            run_id=str(run_id),
            workspace_id=str(workspace_id),
        )

        if hasattr(self._export_service, "export_run_as_docx"):
            export = await self._export_service.export_run_as_docx(
                run_id=run_id,
                workspace_id=workspace_id,
                exported_by="workflow",
                document_ids=state.image_document_ids,
            )
        elif hasattr(self._export_service, "export_run"):
            export = await self._export_service.export_run(
                run_id=run_id,
                workspace_id=workspace_id,
            )
        else:
            raise ValueError(f"Export service does not support exporting run {run_id}")

        logger.info(
            "tariff_export_stage_completed",
            export_id=str(export.id),
            filename=export.filename,
        )

        # Embed product images into the downloaded DOCX (post-processing).
        # SuperDocs cannot access our local filesystem, so we inject the
        # actual image bytes after the file has been downloaded.
        if (
            export.format in ("docx", None)
            and state.image_document_ids
            and self._document_repository is not None
            and self._storage_backend is not None
        ):
            await self._embed_product_images(
                docx_path=export.storage_path,
                image_document_ids=state.image_document_ids,
            )

        return {"export_completed": True, "export_id": str(export.id)}

    async def _embed_product_images(
        self,
        docx_path: str,
        image_document_ids: List[str],
    ) -> None:
        """Load image bytes from local storage and embed them in the DOCX."""
        from backend.core.export.docx_image_embedder import embed_images_in_docx

        images: List[Dict[str, Any]] = []
        for doc_id in image_document_ids:
            try:
                doc = await self._document_repository.get_by_id(UUID(doc_id))
                if doc is None:
                    logger.warning("image_document_not_found", document_id=doc_id)
                    continue
                img_bytes = self._storage_backend.read(doc.storage_path)
                images.append({"bytes": img_bytes, "filename": doc.filename})
            except Exception as exc:
                logger.warning(
                    "image_load_failed",
                    document_id=doc_id,
                    error=str(exc),
                )

        if not images:
            logger.info("no_product_images_loaded", count=len(image_document_ids))
            return

        try:
            embedded = embed_images_in_docx(docx_path, images)
            logger.info(
                "product_images_embed_result",
                embedded=embedded,
                image_count=len(images),
                docx_path=docx_path,
            )
        except Exception as exc:
            # Never fail the export because of image embedding
            logger.warning(
                "product_images_embed_error",
                error=str(exc),
                docx_path=docx_path,
            )
