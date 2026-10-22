from app.services.bates_assignment import (
    BatesAssignmentService,
    format_bates_number,
    parse_bates_number,
)
from app.services.ingestion import (
    FileValidationError,
    IngestionResult,
    IngestionService,
)
from app.services.packet_builder import BuildResult, PacketBuilderService
from app.services.redaction import (
    RedactionApplicationService,
    RedactionDetectionService,
    RedactionMatch,
)
from app.services.superdocs_adapter import SuperDocsAPIError, SuperDocsRESTAdapter
from app.services.superdocs_integration import SuperDocsIntegrationService
from app.services.superdocs_port import (
    AttachmentUploadResult,
    ChatResult,
    DocumentUploadResult,
    ExportResult,
    JobStatus,
    ProposedChange,
    ProposedChangeBatch,
    SuperDocsPort,
)

__all__ = [
    "SuperDocsPort",
    "DocumentUploadResult",
    "AttachmentUploadResult",
    "JobStatus",
    "ProposedChange",
    "ProposedChangeBatch",
    "ChatResult",
    "ExportResult",
    "SuperDocsRESTAdapter",
    "SuperDocsAPIError",
    "BatesAssignmentService",
    "format_bates_number",
    "parse_bates_number",
    "IngestionService",
    "IngestionResult",
    "FileValidationError",
    "SuperDocsIntegrationService",
    "RedactionDetectionService",
    "RedactionApplicationService",
    "RedactionMatch",
    "PacketBuilderService",
    "BuildResult",
]
