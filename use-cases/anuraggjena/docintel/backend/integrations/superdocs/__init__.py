"""
SuperDocs integration layer.

Provides clean integration boundary between DocIntel intelligence and
SuperDocs document content management.
"""

from backend.integrations.superdocs.client import SuperDocsClient
from backend.integrations.superdocs.session_manager import SessionManager
from backend.integrations.superdocs.document_bridge import DocumentBridge
from backend.integrations.superdocs.instruction_builder import InstructionBuilder
from backend.integrations.superdocs.approval_handler import ApprovalHandler
from backend.integrations.superdocs.export_service import ExportService

__all__ = [
    "SuperDocsClient",
    "SessionManager",
    "DocumentBridge",
    "InstructionBuilder",
    "ApprovalHandler",
    "ExportService",
]
