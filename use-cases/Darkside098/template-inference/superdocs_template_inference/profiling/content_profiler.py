"""Content profiler."""

from superdocs_template_inference.models import Document, ParagraphBlock, ContentProfile
from superdocs_template_inference.profiling.utils import (
    calculate_avg_word_length,
    calculate_word_count,
    extract_vocabulary,
)


class ContentProfiler:
    """Extracts content signals from a document."""

    def profile(self, document: Document) -> ContentProfile:
        """Generate content profile from document.

        Args:
            document: Normalized document.

        Returns:
            ContentProfile with content signals.
        """
        blocks = document.blocks

        # Extract all text and headings
        all_text_parts: list[str] = []
        heading_texts: list[str] = []

        for block in blocks:
            if isinstance(block, ParagraphBlock):
                all_text_parts.append(block.text)
                if block.is_heading:
                    heading_texts.append(block.text)

        # Concatenate all text
        full_text = " ".join(all_text_parts)

        # Calculate basic statistics
        total_text_length = len(full_text)
        word_count = calculate_word_count(full_text)

        # Extract vocabulary
        vocabulary, top_vocabulary = extract_vocabulary(full_text, top_n=20)
        unique_words_count = len(vocabulary)

        # Calculate text statistics
        avg_word_length = calculate_avg_word_length(full_text)
        unique_to_total_ratio = word_count / word_count if word_count > 0 else 0.0
        if word_count > 0:
            unique_to_total_ratio = unique_words_count / word_count

        text_statistics = {
            "avg_word_length": round(avg_word_length, 2),
            "unique_to_total_ratio": round(unique_to_total_ratio, 3),
        }

        return ContentProfile(
            total_text_length=total_text_length,
            word_count=word_count,
            unique_words_count=unique_words_count,
            heading_texts=heading_texts,
            vocabulary=vocabulary,
            top_vocabulary=top_vocabulary,
            text_statistics=text_statistics,
        )
