"""Formatting profiler."""

from superdocs_template_inference.models import Document, ParagraphBlock, TableBlock, FormattingProfile


class FormattingProfiler:
    """Extracts formatting signals from a document."""

    def profile(self, document: Document) -> FormattingProfile:
        """Generate formatting profile from document.

        Args:
            document: Normalized document.

        Returns:
            FormattingProfile with formatting signals.
        """
        blocks = document.blocks

        paragraph_styles: dict[str, int] = {}
        heading_styles: dict[str, int] = {}
        has_tables = False
        has_lists = False
        has_headings = False

        for block in blocks:
            if isinstance(block, ParagraphBlock):
                # Extract style name
                if block.style_name:
                    paragraph_styles[block.style_name] = (
                        paragraph_styles.get(block.style_name, 0) + 1
                    )

                # Track heading styles
                if block.is_heading:
                    has_headings = True
                    if block.style_name:
                        heading_styles[block.style_name] = (
                            heading_styles.get(block.style_name, 0) + 1
                        )

                # Track lists
                if block.is_list:
                    has_lists = True

            elif isinstance(block, TableBlock):
                has_tables = True

        return FormattingProfile(
            paragraph_styles=paragraph_styles,
            heading_styles=heading_styles,
            has_tables=has_tables,
            has_lists=has_lists,
            has_headings=has_headings,
        )
