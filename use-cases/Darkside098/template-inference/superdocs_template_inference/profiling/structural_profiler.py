"""Structural profiler."""

from typing import Optional

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock, StructuralProfile


class StructuralProfiler:
    """Extracts structural characteristics from a document."""

    def profile(self, document: Document) -> StructuralProfile:
        """Generate structural profile from document.

        Args:
            document: Normalized document.

        Returns:
            StructuralProfile with structural characteristics.
        """
        blocks = document.blocks

        # Count blocks by type
        total_blocks = len(blocks)
        paragraph_count = 0
        heading_count = 0
        table_count = 0
        list_item_count = 0

        heading_levels: dict[int, int] = {}
        block_type_sequence: list[str] = []
        paragraph_lengths: list[int] = []
        table_dimensions: list[tuple[int, int]] = []
        list_depth_max: Optional[int] = None
        ordered_list_count = 0
        unordered_list_count = 0

        for block in blocks:
            block_type_sequence.append(block.block_type)

            if isinstance(block, ParagraphBlock):
                paragraph_count += 1
                paragraph_lengths.append(len(block.text))

                if block.is_heading:
                    heading_count += 1
                    if block.heading_level is not None:
                        heading_levels[block.heading_level] = (
                            heading_levels.get(block.heading_level, 0) + 1
                        )

                if block.is_list:
                    list_item_count += 1
                    if block.list_level is not None:
                        if list_depth_max is None:
                            list_depth_max = block.list_level
                        else:
                            list_depth_max = max(list_depth_max, block.list_level)

                    if block.list_ordered is True:
                        ordered_list_count += 1
                    elif block.list_ordered is False:
                        unordered_list_count += 1

            elif isinstance(block, TableBlock):
                table_count += 1
                table_dimensions.append((block.num_rows, block.num_cols))

        # Calculate statistics
        avg_paragraph_length = (
            sum(paragraph_lengths) / len(paragraph_lengths)
            if paragraph_lengths
            else 0.0
        )
        min_paragraph_length = min(paragraph_lengths) if paragraph_lengths else 0
        max_paragraph_length = max(paragraph_lengths) if paragraph_lengths else 0

        avg_table_rows = (
            sum(dims[0] for dims in table_dimensions) / len(table_dimensions)
            if table_dimensions
            else None
        )
        avg_table_cols = (
            sum(dims[1] for dims in table_dimensions) / len(table_dimensions)
            if table_dimensions
            else None
        )

        max_heading_level = max(heading_levels.keys()) if heading_levels else None

        return StructuralProfile(
            total_blocks=total_blocks,
            paragraph_count=paragraph_count,
            heading_count=heading_count,
            table_count=table_count,
            list_item_count=list_item_count,
            heading_levels=heading_levels,
            max_heading_level=max_heading_level,
            table_dimensions=table_dimensions,
            avg_table_rows=avg_table_rows,
            avg_table_cols=avg_table_cols,
            block_type_sequence=block_type_sequence,
            paragraph_lengths=paragraph_lengths,
            avg_paragraph_length=avg_paragraph_length,
            min_paragraph_length=min_paragraph_length,
            max_paragraph_length=max_paragraph_length,
            list_depth_max=list_depth_max,
            ordered_list_count=ordered_list_count,
            unordered_list_count=unordered_list_count,
        )
