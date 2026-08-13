from .base import DocumentAdapter
from .docx import parse_docx
from .latex import parse_latex

__all__ = [
    "DocumentAdapter",
    "parse_docx",
    "parse_latex",
]
