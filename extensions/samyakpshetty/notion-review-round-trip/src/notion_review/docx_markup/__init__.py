"""Read a reviewer's marked-up Word file: tracked changes and comments, with attribution.

The reviewer works entirely in Word; this package is how the integration understands what they
did. It parses raw OOXML (python-docx does not expose tracked changes) behind zip-bomb and XXE
defenses, because the returned .docx is untrusted input.
"""

from notion_review.docx_markup.models import DocxComment, DocxMarkup, ParagraphMarkup
from notion_review.docx_markup.parser import parse_docx
from notion_review.docx_markup.security import DocxError, DocxSecurityError

__all__ = [
    "DocxComment",
    "DocxError",
    "DocxMarkup",
    "DocxSecurityError",
    "ParagraphMarkup",
    "parse_docx",
]
