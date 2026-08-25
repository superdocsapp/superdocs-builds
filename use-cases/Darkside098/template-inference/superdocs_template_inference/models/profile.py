"""Document profile data models."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StructuralProfile:
    """Observable structural characteristics of a document."""

    total_blocks: int
    paragraph_count: int
    heading_count: int
    table_count: int
    list_item_count: int

    heading_levels: dict[int, int]  # {level: count}
    max_heading_level: Optional[int]

    table_dimensions: list[tuple[int, int]]  # [(rows, cols), ...]
    avg_table_rows: Optional[float]
    avg_table_cols: Optional[float]

    block_type_sequence: list[str]  # ["paragraph", "table", ...]

    paragraph_lengths: list[int]
    avg_paragraph_length: float
    min_paragraph_length: int
    max_paragraph_length: int

    list_depth_max: Optional[int]
    ordered_list_count: int
    unordered_list_count: int


@dataclass
class ContentProfile:
    """Content signals extracted from document."""

    total_text_length: int
    word_count: int
    unique_words_count: int

    heading_texts: list[str]

    vocabulary: dict[str, int]  # {term: frequency}
    top_vocabulary: list[tuple[str, int]]  # [(term, freq), ...]

    text_statistics: dict = field(
        default_factory=lambda: {
            "avg_word_length": 0.0,
            "unique_to_total_ratio": 0.0,
        }
    )


@dataclass
class FormattingProfile:
    """Formatting signals available from normalized document."""

    paragraph_styles: dict[str, int]  # {style_name: count}
    heading_styles: dict[str, int]  # {style_name: count}

    has_tables: bool
    has_lists: bool
    has_headings: bool


@dataclass
class DetectedSection:
    """A detected section within a document."""

    section_id: str
    start_block_idx: int
    end_block_idx: int

    title: Optional[str]  # Heading text if available
    heading_level: Optional[int]  # Level of section-starting heading

    block_count: int
    paragraph_count: int
    table_count: int

    content_length: int

    boundary_marker: str  # "heading", "document_start", "document_end"


@dataclass
class DocumentProfile:
    """Comprehensive profile of a normalized document."""

    profile_id: str
    document_id: str
    filename: str
    file_type: str  # "docx" or "pdf"

    structural: StructuralProfile
    content: ContentProfile
    formatting: FormattingProfile

    sections: list[DetectedSection] = field(default_factory=list)

    profiled_at: str = ""  # ISO 8601 timestamp
    profile_version: str = "1.0"
