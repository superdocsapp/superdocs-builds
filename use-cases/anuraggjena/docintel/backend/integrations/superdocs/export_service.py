"""
SuperDocs Export Service.

Orchestrates document export via SuperDocs with local storage.
"""

import httpx
from pathlib import Path
from typing import Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timezone

from backend.integrations.superdocs.client import SuperDocsClient
from backend.integrations.superdocs.session_manager import SessionManager
from backend.repositories.export import ExportRepository
from backend.models.export import Export
from backend.config import settings
from backend.logging_config import get_logger

logger = get_logger(__name__)


class ExportService:
    """
    Handles document export via SuperDocs.

    Responsibilities:
    - Export documents from SuperDocs sessions
    - Download exported files from pre-signed URLs
    - Store exports in DocIntel local storage
    - Create Export records for tracking
    """

    def __init__(
        self,
        superdocs_client: SuperDocsClient,
        session_manager: SessionManager,
        export_repository: ExportRepository,
        storage_base_path: str = "storage/exports"
    ):
        """
        Initialize export service.

        Args:
            superdocs_client: SuperDocs API client
            session_manager: Session manager
            export_repository: Export repository
            storage_base_path: Base path for export storage
        """
        self.client = superdocs_client
        self.session_manager = session_manager
        self.export_repo = export_repository
        self.storage_base_path = Path(storage_base_path)

        # Ensure storage directory exists
        self.storage_base_path.mkdir(parents=True, exist_ok=True)

    async def export_run(
        self,
        run_id: UUID,
        workspace_id: UUID,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None
    ) -> Export:
        """
        Export workflow run document via SuperDocs.

        Args:
            run_id: Workflow run ID
            workspace_id: Workspace ID
            format: Export format ("docx", "pdf", "html", "markdown", "txt")
            options: Optional export options

        Returns:
            Export record with local storage path

        Raises:
            ValueError: If no session exists for run
            Exception: If export fails
        """
        logger.info(
            "exporting_run",
            run_id=str(run_id),
            format=format
        )

        # Get session ID
        session_id = await self.session_manager.get_session_for_run(run_id)

        if not session_id:
            raise ValueError(f"No SuperDocs session found for run {run_id}")

        # Request export from SuperDocs
        export_result = await self.client.request_download_url(
            session_id=session_id,
            format=format,
            options=options
        )

        # Download file from pre-signed URL
        storage_path = await self._download_and_store(
            download_url=export_result.download_url,
            filename=export_result.filename,
            run_id=run_id
        )

        # Get file size
        file_size = Path(storage_path).stat().st_size

        # Create export record
        export = await self.export_repo.create(
            workspace_id=workspace_id,
            workflow_run_id=run_id,
            review_id=None,  # Optional, could be added if needed
            format=format,
            filename=export_result.filename,
            storage_path=storage_path,
            file_size=file_size,
            exported_by="superdocs"
        )

        logger.info(
            "export_created",
            export_id=str(export.id),
            format=format,
            file_size=file_size
        )

        return export

    async def _download_and_store(
        self,
        download_url: str,
        filename: str,
        run_id: UUID
    ) -> str:
        """
        Download file from pre-signed URL and store locally.

        Args:
            download_url: Pre-signed download URL
            filename: Filename for storage
            run_id: Workflow run ID (for organizing storage)

        Returns:
            Storage path (relative)

        Raises:
            httpx.HTTPError: If download fails
        """
        logger.info(
            "downloading_export",
            filename=filename,
            run_id=str(run_id)
        )

        # Create run-specific directory
        run_dir = self.storage_base_path / str(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        # Generate storage path
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        storage_filename = f"{timestamp}_{filename}"
        storage_path = run_dir / storage_filename

        # Download file
        async with httpx.AsyncClient(timeout=300.0) as client:
            response = await client.get(download_url)
            response.raise_for_status()

            # Write to storage
            with open(storage_path, "wb") as f:
                f.write(response.content)

        logger.info(
            "export_downloaded",
            storage_path=str(storage_path),
            size_bytes=len(response.content)
        )

        # Return absolute path for reliable resolution across CWD contexts
        return str(storage_path.resolve())

    async def export_with_fallback(
        self,
        run_id: UUID,
        workspace_id: UUID,
        format: str = "docx",
        options: Optional[Dict[str, Any]] = None,
        use_internal_fallback: bool = True
    ) -> Export:
        """
        Export with fallback to internal generator if SuperDocs fails.

        Args:
            run_id: Workflow run ID
            workspace_id: Workspace ID
            format: Export format
            options: Export options
            use_internal_fallback: If True, fall back to internal generator

        Returns:
            Export record

        Raises:
            Exception: If both SuperDocs and fallback fail
        """
        try:
            # Try SuperDocs export first
            return await self.export_run(
                run_id=run_id,
                workspace_id=workspace_id,
                format=format,
                options=options
            )

        except Exception as exc:
            logger.warning(
                "superdocs_export_failed",
                run_id=str(run_id),
                error=str(exc),
                will_fallback=use_internal_fallback
            )

            if not use_internal_fallback:
                raise

            # Fall back to internal generator
            logger.info(
                "using_internal_export_fallback",
                run_id=str(run_id)
            )

            # TODO: Call internal DOCXGenerator as fallback
            # This preserves existing export functionality
            # from backend.services.export import ExportService as InternalExportService
            # return await internal_service.export_run(...)

            raise NotImplementedError("Internal export fallback not yet implemented")

    async def get_export_download_path(self, export_id: UUID) -> Optional[str]:
        """
        Get local file path for export download.

        Args:
            export_id: Export record ID

        Returns:
            Absolute file path if export exists, None otherwise
        """
        export = await self.export_repo.get_by_id(export_id)

        if not export:
            return None

        path = Path(export.storage_path)

        if not path.exists():
            logger.error(
                "export_file_missing",
                export_id=str(export_id),
                path=str(path)
            )
            return None

        return str(path.absolute())
