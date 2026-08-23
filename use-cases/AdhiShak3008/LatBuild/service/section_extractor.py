"""
section_extractor.py
Extract clean prose from a section for sending to SuperDocs.

Responsibilities:
- Produce clean plain text from a Section's content blocks
- Report word count and estimated character budget
- Preserve non-content element positions (figures, tables never touched)

SuperDocs receives ONLY clean prose. It has no idea the text came from a PDF,
which page it came from, or what columns it occupied. That is intentional.
"""

from dataclasses import dataclass
from typing import List

from flow_mapper import Section, DocumentFlowMap
from pdf_analyzer import NonContentElement, DocumentGrammar


@dataclass
class ExtractedSection:
    section_name: str
    clean_text: str
    word_count: int
    char_count: int
    estimated_lines: int          # how many lines the original occupied
    estimated_height_pts: float   # total vertical space in points


def extract_section(section: Section, grammar: DocumentGrammar) -> ExtractedSection:
    """
    Extract clean prose from a section.
    Returns the text SuperDocs will receive.
    """
    clean_text = section.full_text.strip()

    word_count = len(clean_text.split()) if clean_text else 0
    char_count = len(clean_text)

    # Estimate lines and height from flow regions
    total_height = sum(r.bbox.height for r in section.flow_regions)
    estimated_lines = max(1, int(total_height / grammar.body_line_height))

    return ExtractedSection(
        section_name=section.title,
        clean_text=clean_text,
        word_count=word_count,
        char_count=char_count,
        estimated_lines=estimated_lines,
        estimated_height_pts=total_height,
    )


def extract_multiple_sections(
    sections: List[Section], grammar: DocumentGrammar
) -> List[ExtractedSection]:
    """Extract multiple sections independently."""
    return [extract_section(s, grammar) for s in sections]


def build_superdocs_instruction(
    user_instruction: str,
    extracted: ExtractedSection,
    full_document_text: str = "",
    include_word_hint: bool = True,
) -> str:
    """
    Build the instruction string sent to SuperDocs.

    Lean approach: just the user instruction + a minimal preservation note.
    The uploaded document IS the section — SuperDocs knows to edit that.
    Full document context goes in as brief background only when provided.
    """
    parts = []

    # Optional brief context (paper summary, not the full doc)
    if full_document_text:
        doc_words = full_document_text.split()
        if len(doc_words) > 6000:
            context_text = " ".join(doc_words[:6000]) + "\n[truncated]"
        else:
            context_text = full_document_text
        parts.append(
            f"Background context (read-only, do not reproduce in output):\n{context_text}"
        )

    # The actual instruction
    parts.append(user_instruction)

    if include_word_hint and extracted.word_count > 0:
        parts.append(
            f"IMPORTANT: The original text is approximately {extracted.word_count} words ({extracted.char_count} characters). "
            f"Your rewritten version MUST be approximately the same length (~{extracted.word_count} words, ±5%) "
            f"to seamlessly fill the document layout without leaving empty blank spaces or causing overflow."
        )

    return "\n\n".join(parts)
