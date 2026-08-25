"""Normalized document representation."""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Block:
    """Base class for document content blocks."""

    block_type: str


@dataclass
class ParagraphBlock(Block):
    """A paragraph with optional formatting metadata."""

    block_type: str = "paragraph"
    text: str = ""
    style_name: Optional[str] = None
    is_heading: bool = False
    heading_level: Optional[int] = None  # 1-6 if heading, None otherwise
    is_list: bool = False
    list_level: Optional[int] = None  # Nesting level if list, None otherwise
    list_ordered: Optional[bool] = None  # True if ordered, False if unordered, None if not list
    font_name: Optional[str] = None
    font_size: Optional[float] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None
    underline: Optional[bool] = None
    alignment: Optional[str] = None
    spacing_before: Optional[float] = None
    spacing_after: Optional[float] = None
    indent_left: Optional[float] = None
    indent_first_line: Optional[float] = None


@dataclass
class TableBlock(Block):
    """A table with row and column structure."""

    block_type: str = "table"
    rows: list[list[str]] = field(default_factory=list)

    @property
    def num_rows(self) -> int:
        """Return the number of rows in the table."""
        return len(self.rows)

    @property
    def num_cols(self) -> int:
        """Return the number of columns in the table.
        
        Returns 0 if the table is empty.
        Uses the first row to determine column count.
        """
        if not self.rows:
            return 0
        return len(self.rows[0])


@dataclass
class Document:
    """Normalized document representation independent of source format."""

    document_id: str
    filename: str
    file_type: str  # "docx" or "pdf"
    loaded_at: str  # ISO 8601 timestamp
    blocks: list[Block] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate document after initialization."""
        if self.file_type not in ("docx", "pdf"):
            raise ValueError(f"Invalid file_type: {self.file_type}")
