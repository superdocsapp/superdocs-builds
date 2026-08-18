"""Assembler package for M&A Closing-Binder Assembler."""

from .pdf_binder import PDFBinderAssembler
from .styles import get_legal_binder_styles

__all__ = ["PDFBinderAssembler", "get_legal_binder_styles"]
