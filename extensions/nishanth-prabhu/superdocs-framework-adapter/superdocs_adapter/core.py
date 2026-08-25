from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from .models import ToolName, ToolResult


class SuperDocsAdapter(ABC):
    """Framework-independent interface for SuperDocs document operations.

    Framework-specific integrations must depend on this interface rather than
    directly coupling themselves to SuperDocs implementation details.
    """

    @abstractmethod
    def edit_document(
        self,
        document_id: str,
        instruction: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Apply an instruction-driven edit to a document."""
        raise NotImplementedError

    @abstractmethod
    def search_document(
        self,
        document_id: str,
        query: str,
        **kwargs: Any,
    ) -> ToolResult:
        """Search a document for information relevant to a query."""
        raise NotImplementedError

    @abstractmethod
    def export_document(
        self,
        document_id: str,
        format: str = "docx",
        **kwargs: Any,
    ) -> ToolResult:
        """Export a document in the requested format."""
        raise NotImplementedError
