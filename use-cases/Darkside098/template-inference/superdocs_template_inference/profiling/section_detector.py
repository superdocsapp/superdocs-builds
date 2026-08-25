"""Section detector."""

from uuid import uuid4

from superdocs_template_inference.models import Document, ParagraphBlock, DetectedSection


class SectionDetector:
    """Detects sections based on heading boundaries."""

    def detect_sections(self, document: Document) -> list[DetectedSection]:
        """Detect sections in a document.

        Sections are identified by heading blocks.
        - Document start establishes first section
        - Each heading block closes previous section and starts new one
        - Document end closes final section

        Args:
            document: Normalized document.

        Returns:
            List of detected sections. Empty if document is empty.
        """
        blocks = document.blocks

        if not blocks:
            return []

        sections: list[DetectedSection] = []
        current_section_start = 0
        current_section_heading_idx: int | None = None

        for i, block in enumerate(blocks):
            is_heading = isinstance(block, ParagraphBlock) and block.is_heading

            if is_heading:
                # Close previous section if any
                if current_section_start < i:
                    section = self._create_section(
                        blocks,
                        current_section_start,
                        i - 1,
                        current_section_heading_idx,
                    )
                    sections.append(section)

                # Start new section at this heading
                current_section_start = i
                current_section_heading_idx = i

        # Close final section
        if current_section_start < len(blocks):
            section = self._create_section(
                blocks, current_section_start, len(blocks) - 1, current_section_heading_idx
            )
            sections.append(section)

        return sections

    def _create_section(
        self,
        blocks: list,
        start_idx: int,
        end_idx: int,
        heading_idx: int | None,
    ) -> DetectedSection:
        """Create a DetectedSection from block range.

        Args:
            blocks: List of all blocks.
            start_idx: Start block index (inclusive).
            end_idx: End block index (inclusive).
            heading_idx: Index of heading block (if any).

        Returns:
            DetectedSection object.
        """
        section_blocks = blocks[start_idx : end_idx + 1]

        # Count blocks by type and text
        paragraph_count = 0
        table_count = 0
        content_length = 0
        title: str | None = None
        heading_level: int | None = None

        for block in section_blocks:
            if isinstance(block, ParagraphBlock):
                paragraph_count += 1
                content_length += len(block.text)
                if block.is_heading and heading_idx is not None:
                    title = block.text
                    heading_level = block.heading_level
            else:
                table_count += 1

        # Determine boundary marker
        if heading_idx is not None:
            boundary_marker = "heading"
        elif start_idx == 0:
            boundary_marker = "document_start"
        else:
            boundary_marker = "document_end"

        return DetectedSection(
            section_id=str(uuid4()),
            start_block_idx=start_idx,
            end_block_idx=end_idx,
            title=title,
            heading_level=heading_level,
            block_count=len(section_blocks),
            paragraph_count=paragraph_count,
            table_count=table_count,
            content_length=content_length,
            boundary_marker=boundary_marker,
        )
