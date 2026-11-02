"""Abstract base interface for Wiki hosts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from live_doc_agent.models import Patch, WikiDocument


class WikiAdapter(ABC):
    """Abstract interface defining the contract for wiki platforms (Nuclino, Quip, In-Memory)."""

    @abstractmethod
    def fetch_page(self, doc_id: str) -> WikiDocument:
        """Fetch the current document content, sections, and version token.

        Args:
            doc_id: Target document identifier.

        Returns:
            WikiDocument snapshot.
        """
        raise NotImplementedError

    @abstractmethod
    def apply_patch(self, doc_id: str, patch: Patch) -> WikiDocument:
        """Surgically apply a validated patch to the document.

        Must verify `patch.expected_version` matches current remote version.
        Raises `ConflictError` if version mismatch occurs.

        Args:
            doc_id: Target document identifier.
            patch: The validated Patch to apply.

        Returns:
            Updated WikiDocument snapshot.
        """
        raise NotImplementedError

    @abstractmethod
    def get_version(self, doc_id: str) -> str:
        """Get the current content version of the document.

        Args:
            doc_id: Target document identifier.

        Returns:
            Version string or token.
        """
        raise NotImplementedError
