"""Document ingestion components."""

from .docx_loader import DOCXLoader
from .loader import DocumentLoader

__all__ = [
    "DocumentLoader",
    "DOCXLoader",
]
