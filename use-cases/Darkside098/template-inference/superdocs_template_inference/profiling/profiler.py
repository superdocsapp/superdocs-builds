"""Main document profiler."""

import json
from datetime import datetime
from uuid import uuid4

from superdocs_template_inference.models import Document, DocumentProfile
from superdocs_template_inference.profiling.content_profiler import ContentProfiler
from superdocs_template_inference.profiling.formatting_profiler import FormattingProfiler
from superdocs_template_inference.profiling.section_detector import SectionDetector
from superdocs_template_inference.profiling.structural_profiler import StructuralProfiler


class DocumentProfiler:
    """Main orchestrator for document profiling."""

    def __init__(self):
        """Initialize profiler with component profilers."""
        self.structural_profiler = StructuralProfiler()
        self.content_profiler = ContentProfiler()
        self.formatting_profiler = FormattingProfiler()
        self.section_detector = SectionDetector()

    def profile(self, document: Document) -> DocumentProfile:
        """Generate comprehensive profile from a normalized document.

        Args:
            document: Normalized Document from ingestion.

        Returns:
            DocumentProfile with structural, content, formatting, and section data.
        """
        # Generate unique profile ID
        profile_id = str(uuid4())

        # Profile each aspect
        structural = self.structural_profiler.profile(document)
        content = self.content_profiler.profile(document)
        formatting = self.formatting_profiler.profile(document)
        sections = self.section_detector.detect_sections(document)

        # Timestamp
        profiled_at = datetime.utcnow().isoformat() + "Z"

        return DocumentProfile(
            profile_id=profile_id,
            document_id=document.document_id,
            filename=document.filename,
            file_type=document.file_type,
            structural=structural,
            content=content,
            formatting=formatting,
            sections=sections,
            profiled_at=profiled_at,
            profile_version="1.0",
        )

    def to_dict(self, profile: DocumentProfile) -> dict:
        """Serialize profile to dictionary.

        Args:
            profile: DocumentProfile to serialize.

        Returns:
            Dictionary representation of profile.
        """
        return {
            "profile_id": profile.profile_id,
            "document_id": profile.document_id,
            "filename": profile.filename,
            "file_type": profile.file_type,
            "structural": {
                "total_blocks": profile.structural.total_blocks,
                "paragraph_count": profile.structural.paragraph_count,
                "heading_count": profile.structural.heading_count,
                "table_count": profile.structural.table_count,
                "list_item_count": profile.structural.list_item_count,
                "heading_levels": profile.structural.heading_levels,
                "max_heading_level": profile.structural.max_heading_level,
                "table_dimensions": profile.structural.table_dimensions,
                "avg_table_rows": profile.structural.avg_table_rows,
                "avg_table_cols": profile.structural.avg_table_cols,
                "block_type_sequence": profile.structural.block_type_sequence,
                "paragraph_lengths": profile.structural.paragraph_lengths,
                "avg_paragraph_length": round(profile.structural.avg_paragraph_length, 2),
                "min_paragraph_length": profile.structural.min_paragraph_length,
                "max_paragraph_length": profile.structural.max_paragraph_length,
                "list_depth_max": profile.structural.list_depth_max,
                "ordered_list_count": profile.structural.ordered_list_count,
                "unordered_list_count": profile.structural.unordered_list_count,
            },
            "content": {
                "total_text_length": profile.content.total_text_length,
                "word_count": profile.content.word_count,
                "unique_words_count": profile.content.unique_words_count,
                "heading_texts": profile.content.heading_texts,
                "vocabulary": profile.content.vocabulary,
                "top_vocabulary": profile.content.top_vocabulary,
                "text_statistics": profile.content.text_statistics,
            },
            "formatting": {
                "paragraph_styles": profile.formatting.paragraph_styles,
                "heading_styles": profile.formatting.heading_styles,
                "has_tables": profile.formatting.has_tables,
                "has_lists": profile.formatting.has_lists,
                "has_headings": profile.formatting.has_headings,
            },
            "sections": [
                {
                    "section_id": section.section_id,
                    "start_block_idx": section.start_block_idx,
                    "end_block_idx": section.end_block_idx,
                    "title": section.title,
                    "heading_level": section.heading_level,
                    "block_count": section.block_count,
                    "paragraph_count": section.paragraph_count,
                    "table_count": section.table_count,
                    "content_length": section.content_length,
                    "boundary_marker": section.boundary_marker,
                }
                for section in profile.sections
            ],
            "profiled_at": profile.profiled_at,
            "profile_version": profile.profile_version,
        }

    def to_json(self, profile: DocumentProfile) -> str:
        """Serialize profile to JSON string.

        Args:
            profile: DocumentProfile to serialize.

        Returns:
            JSON string representation of profile.
        """
        return json.dumps(self.to_dict(profile), indent=2)
