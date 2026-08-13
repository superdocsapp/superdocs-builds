from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ..document import Document


class DocumentAdapter(ABC):
    """
    Interface for document-format adapters.

    Each adapter converts a source document into DocShield's
    normalized Document representation.
    """

    extensions: tuple[str, ...] = ()

    @abstractmethod
    def parse(self, path: str | Path) -> Document:
        """Parse a document into the normalized representation."""
        raise NotImplementedError

    def supports(self, path: str | Path) -> bool:
        """Return True when this adapter supports the file extension."""
        return Path(path).suffix.lower() in self.extensions