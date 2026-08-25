"""Document-aware semantic section detection for M7."""

import re
from typing import Optional
from uuid import uuid4

from superdocs_template_inference.models import (
    DetectedSection,
    Document,
    ParagraphBlock,
    TableBlock,
)


def _extract_table_keywords(table: TableBlock) -> set[str]:
    """Extract lowercase keywords from all table cells.

    Args:
        table: TableBlock to analyze.

    Returns:
        Set of lowercase words found in table cells.
    """
    keywords = set()
    for row in table.rows:
        for cell in row:
            if cell:
                words = re.findall(r'\b\w+\b', cell.lower())
                keywords.update(words)
    return keywords


def _detect_employee_information_table(table: TableBlock) -> bool:
    """Check if table appears to contain employee information.

    Looks for keywords like: employee, id, position, department, team, role, etc.

    Args:
        table: TableBlock to analyze.

    Returns:
        True if table appears to be employee information.
    """
    keywords = _extract_table_keywords(table)
    employee_keywords = {
        "employee", "id", "position", "department", "team", "role",
        "title", "manager", "supervisor", "name", "email", "phone"
    }
    return bool(keywords & employee_keywords)


def _detect_first_day_table(table: TableBlock) -> bool:
    """Check if table appears to contain first-day information.

    Looks for keywords like: start, date, arrival, time, location, work mode, etc.

    Args:
        table: TableBlock to analyze.

    Returns:
        True if table appears to be first-day information.
    """
    keywords = _extract_table_keywords(table)
    first_day_keywords = {
        "start", "date", "arrival", "time", "location", "address",
        "work", "mode", "remote", "office", "hybrid", "building",
        "desk", "welcome"
    }
    return bool(keywords & first_day_keywords)


def _detect_orientation_table(table: TableBlock) -> bool:
    """Check if table appears to contain orientation information.

    Looks for keywords like: orientation, training, schedule, etc.

    Args:
        table: TableBlock to analyze.

    Returns:
        True if table appears to be orientation information.
    """
    keywords = _extract_table_keywords(table)
    orientation_keywords = {
        "orientation", "training", "onboarding", "schedule", "session",
        "workshop", "course", "learn", "induction"
    }
    return bool(keywords & orientation_keywords)


def _get_paragraph_context_around_block(
    document: Document,
    block_index: int,
    context_size: int = 2,
) -> str:
    """Get text context from surrounding paragraphs.

    Args:
        document: Document to analyze.
        block_index: Index of the block to get context for.
        context_size: Number of surrounding blocks to include.

    Returns:
        Concatenated text from surrounding paragraphs.
    """
    start = max(0, block_index - context_size)
    end = min(len(document.blocks), block_index + context_size + 1)

    context_parts = []
    for i in range(start, end):
        block = document.blocks[i]
        if isinstance(block, ParagraphBlock) and block.text:
            context_parts.append(block.text)

    return " ".join(context_parts)


def _canonical_semantic_title(text: str) -> Optional[str]:
    """Map heading-like text to a reusable semantic title whenever possible."""
    if not text:
        return None

    cleaned = re.sub(r"\s+", " ", text.strip())
    lowered = cleaned.lower()
    compact = re.sub(r"[^a-z0-9]+", " ", lowered).strip()

    aliases = {
        "welcome": "welcome",
        "welcome aboard": "welcome",
        "your role and team": "role_and_department",
        "role and team": "role_and_department",
        "your role": "role_and_department",
        "team": "role_and_department",
        "your first day": "first_day",
        "first day": "first_day",
        "orientation": "orientation",
        "initial training": "initial_training",
        "training": "initial_training",
        "remote work setup": "remote_work_setup",
        "remote work arrangement": "remote_work_setup",
        "technical environment setup": "technical_environment_setup",
        "environment setup": "technical_environment_setup",
        "equipment allocation": "equipment_allocation",
        "before you arrive": "before_you_arrive",
        "questions before you start": "questions_and_contact",
        "questions and contact": "questions_and_contact",
        "questions": "questions_and_contact",
        "contact": "questions_and_contact",
        "closing": "closing_signature",
        "sincerely": "closing_signature",
        "warm regards": "closing_signature",
        "thank you": "closing_signature",
        "good luck": "closing_signature",
        "company header": "company_header",
        "company details": "company_header",
        "company information": "company_header",
        "onboarding title": "onboarding_title",
        "onboarding letter": "onboarding_title",
        "letter date": "letter_date",
        "employee information": "employee_information",
    }

    for phrase, title in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        if phrase in compact:
            return title

    if re.search(r"\b(date|dated)\b", compact):
        return "letter_date"

    if re.search(r"\b(company|office|team)\b", compact):
        return "company_header"

    if re.search(r"\b(onboarding|welcome)\b", compact):
        return "onboarding_title"

    if len(compact.split()) <= 5 and not any(ch in cleaned for ch in ".!?;:"):
        return "section_heading"

    return None


def _looks_like_semantic_heading(text: str, block: Optional[ParagraphBlock] = None) -> bool:
    """Heuristic for standalone semantic headings without Word heading styles."""
    if not text:
        return False

    cleaned = re.sub(r"\s+", " ", text.strip())
    if len(cleaned) > 100:
        return False

    if block is not None and (block.is_heading or (block.style_name and "heading" in block.style_name.lower())):
        return True

    compact = re.sub(r"[^a-z0-9]+", " ", cleaned.lower()).strip()
    if not compact:
        return False

    words = compact.split()
    if len(words) > 10:
        return False

    if any(keyword in compact for keyword in [
        "welcome", "role", "team", "first day", "orientation", "training",
        "remote work", "technical environment", "equipment", "before you arrive",
        "questions", "contact", "department", "onboarding", "company"
    ]):
        return True

    if len(words) <= 5 and not any(ch in cleaned for ch in ".!?;:"):
        if sum(1 for ch in cleaned if ch.isupper()) / max(1, len([c for c in cleaned if c.isalpha()])) >= 0.6:
            return True
        if len(words) <= 4 and all(word[:1].isupper() for word in words if word):
            return True

    return False


def detect_semantic_sections_from_document(
    document: Document,
) -> list[DetectedSection]:
    """Detect semantic sections by analyzing Document blocks directly.

    This function reads actual block content including table cell text to identify
    meaningful semantic zones even when heading styles are absent.
    """
    if not document or not document.blocks:
        return []

    semantic_sections: list[DetectedSection] = []
    anchors: list[tuple[int, str]] = []

    # Early content: company header / date / onboarding title
    early_paragraphs = [
        block.text.strip()
        for block in document.blocks[:min(6, len(document.blocks))]
        if isinstance(block, ParagraphBlock) and block.text and block.text.strip()
    ]
    early_text = " ".join(early_paragraphs).lower()
    if any(keyword in early_text for keyword in ["company", "address", "phone", "email", "contact", "website"]):
        anchors.append((0, "company_header"))
    elif any(keyword in early_text for keyword in ["welcome", "onboarding", "employment", "employee onboarding"]):
        anchors.append((0, "onboarding_title"))

    # Title-like paragraphs and section headers
    for i, block in enumerate(document.blocks):
        if not isinstance(block, ParagraphBlock):
            continue
        text = block.text.strip()
        if not text:
            continue
        title = _canonical_semantic_title(text)
        if title and _looks_like_semantic_heading(text, block):
            anchors.append((i, title))

    # Table-based semantic zones, keeping orientation precedence before first_day
    for i, block in enumerate(document.blocks):
        if not isinstance(block, TableBlock):
            continue
        if _detect_employee_information_table(block):
            anchors.append((i, "employee_information"))
        elif _detect_orientation_table(block):
            anchors.append((i, "orientation"))
        elif _detect_first_day_table(block):
            anchors.append((i, "first_day"))

    # Greeting and closing/signature detection
    for i, block in enumerate(document.blocks):
        if not isinstance(block, ParagraphBlock) or not block.text:
            continue
        text = block.text.strip().lower()
        if re.match(r"^(dear|hello|hi|greetings|welcome)\b", text):
            anchors.append((i, "greeting"))
            break

    for i in range(max(0, len(document.blocks) - 5), len(document.blocks)):
        block = document.blocks[i]
        if isinstance(block, ParagraphBlock) and block.text:
            text = block.text.lower()
            if any(kw in text for kw in ["sincerely", "warm regards", "best regards", "thank you", "yours truly"]):
                anchors.append((i, "closing_signature"))
                break

    # Remove duplicates while preserving document order
    unique_anchors: list[tuple[int, str]] = []
    seen: set[tuple[int, str]] = set()
    for anchor in sorted(anchors, key=lambda item: item[0]):
        key = (anchor[0], anchor[1])
        if key not in seen:
            unique_anchors.append(anchor)
            seen.add(key)

    if not unique_anchors:
        return []

    # Build contiguous, non-overlapping semantic sections from anchor boundaries
    for idx, (start_idx, title) in enumerate(unique_anchors):
        end_idx = unique_anchors[idx + 1][0] - 1 if idx + 1 < len(unique_anchors) else len(document.blocks) - 1
        if end_idx < start_idx:
            continue

        start_idx = max(0, start_idx)
        end_idx = min(len(document.blocks) - 1, end_idx)
        table_count = 0
        paragraph_count = 0
        content_length = 0
        for i in range(start_idx, end_idx + 1):
            block = document.blocks[i]
            if isinstance(block, TableBlock):
                table_count += 1
            elif isinstance(block, ParagraphBlock):
                paragraph_count += 1
                content_length += len(block.text)

        semantic_sections.append(DetectedSection(
            section_id=f"semantic_{str(uuid4())}",
            start_block_idx=start_idx,
            end_block_idx=end_idx,
            title=title,
            heading_level=None,
            block_count=end_idx - start_idx + 1,
            paragraph_count=paragraph_count,
            table_count=table_count,
            content_length=content_length,
            boundary_marker="semantic_pattern",
        ))

    # If there is strong early content before the first anchor, include it as a leading section.
    first_anchor_idx = unique_anchors[0][0]
    if first_anchor_idx > 0:
        early_title = "company_header" if any(keyword in early_text for keyword in ["company", "address", "phone", "email", "contact"]) else "letter_date"
        if early_title:
            section_end = first_anchor_idx - 1
            early_content = " ".join(
                block.text for block in document.blocks[: section_end + 1]
                if isinstance(block, ParagraphBlock) and block.text
            )
            if early_content.strip():
                semantic_sections.insert(
                    0,
                    DetectedSection(
                        section_id=f"semantic_{str(uuid4())}",
                        start_block_idx=0,
                        end_block_idx=section_end,
                        title=early_title,
                        heading_level=None,
                        block_count=section_end + 1,
                        paragraph_count=sum(1 for block in document.blocks[: section_end + 1] if isinstance(block, ParagraphBlock) and block.text),
                        table_count=sum(1 for block in document.blocks[: section_end + 1] if isinstance(block, TableBlock)),
                        content_length=len(early_content),
                        boundary_marker="semantic_pattern",
                    ),
                )

    semantic_sections.sort(key=lambda section: section.start_block_idx)
    return semantic_sections


def merge_sections_preserving_headings(
    profile_sections: list[DetectedSection],
    document_sections: list[DetectedSection],
) -> list[DetectedSection]:
    """Merge document-aware sections with profile sections.

    Preserves heading-based sections from the profile and augments with
    document-detected semantic zones that don't conflict with existing structure.

    Args:
        profile_sections: Sections detected from DocumentProfile.
        document_sections: Sections detected from Document blocks.

    Returns:
        Merged list of DetectedSection objects.
    """
    if not document_sections:
        return profile_sections

    if not profile_sections:
        return document_sections

    heading_sections = [s for s in profile_sections if s.boundary_marker == "heading"]
    document_fallback_sections = [
        s for s in profile_sections
        if s.start_block_idx == 0
        and s.end_block_idx > 0
        and (s.title is None or str(s.title).lower() in {"untitled", "none", "null"})
    ]

    merged = list(heading_sections)

    # A single, untitled full-document fallback should not block valid semantic sections.
    if len(profile_sections) == 1 and document_fallback_sections:
        merged = []

    for doc_section in document_sections:
        has_overlap = any(
            not (doc_section.end_block_idx < s.start_block_idx or doc_section.start_block_idx > s.end_block_idx)
            for s in merged
        )

        if not has_overlap:
            merged.append(doc_section)
        elif document_fallback_sections and any(
            s.start_block_idx == 0 and s.end_block_idx >= doc_section.end_block_idx for s in document_fallback_sections
        ):
            merged = [s for s in merged if s not in document_fallback_sections]
            merged.append(doc_section)

    merged.sort(key=lambda s: s.start_block_idx)
    return merged


def _blocks_overlap(start1: int, end1: int, start2: int, end2: int) -> bool:
    """Check if two block ranges overlap.

    Args:
        start1, end1: First range (inclusive).
        start2, end2: Second range (inclusive).

    Returns:
        True if ranges overlap, False otherwise.
    """
    return not (end1 < start2 or end2 < start1)


def _canonical_title_for_dedup(title: str | None) -> str:
    """Normalize a title for deduplication matching.

    Maps semantic aliases to their canonical form and lowercases.

    Args:
        title: Section title to normalize.

    Returns:
        Canonical lowercase title, or empty string if None.
    """
    if not title:
        return ""

    normalized = str(title).strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    # Map semantic aliases to canonical forms
    aliases = {
        "onboarding_title": "onboarding_title",
        "onboarding_letter": "onboarding_title",
        "letter_title": "onboarding_title",
        "welcome": "welcome",
        "welcome_aboard": "welcome",
        "role_and_department": "role_and_department",
        "role_and_team": "role_and_department",
        "your_role": "role_and_department",
        "team": "role_and_department",
        "first_day": "first_day",
        "your_first_day": "first_day",
        "orientation": "orientation",
        "initial_training": "initial_training",
        "training": "initial_training",
        "remote_work_setup": "remote_work_setup",
        "remote_work_arrangement": "remote_work_setup",
        "technical_environment_setup": "technical_environment_setup",
        "environment_setup": "technical_environment_setup",
        "equipment_allocation": "equipment_allocation",
        "before_you_arrive": "before_you_arrive",
        "questions_and_contact": "questions_and_contact",
        "questions": "questions_and_contact",
        "contact": "questions_and_contact",
        "closing_signature": "closing_signature",
        "closing": "closing_signature",
        "signature": "closing_signature",
        "company_header": "company_header",
        "company_details": "company_header",
        "letter_date": "letter_date",
        "employee_information": "employee_information",
        "greeting": "greeting",
    }

    return aliases.get(normalized, normalized)


def deduplicate_semantic_sections(sections: list[DetectedSection]) -> list[DetectedSection]:
    """Deduplicate semantic sections within a single document.

    Merges sections that:
    - Have overlapping or adjacent block ranges
    - Have the same canonical semantic title

    Preserves the strongest title and widest block range.

    Args:
        sections: List of DetectedSection objects from a single document/profile.

    Returns:
        Deduplicated list with no overlapping semantic sections.
    """
    if not sections:
        return []

    if len(sections) <= 1:
        return sections

    # Sort by start block index
    sorted_sections = sorted(sections, key=lambda s: s.start_block_idx)

    # Track which sections have been merged
    merged_into: dict[int, int] = {}  # original_idx -> merged_into_idx
    deduplicated: list[DetectedSection] = []

    for i, section in enumerate(sorted_sections):
        # Check if this section should be merged with an existing deduplicated section
        merged_flag = False

        for j, dedup_section in enumerate(deduplicated):
            # Check if sections overlap
            if _blocks_overlap(
                section.start_block_idx, section.end_block_idx,
                dedup_section.start_block_idx, dedup_section.end_block_idx
            ):
                # Check if they have the same canonical semantic title
                section_canonical = _canonical_title_for_dedup(section.title)
                dedup_canonical = _canonical_title_for_dedup(dedup_section.title)

                if section_canonical and section_canonical == dedup_canonical:
                    # Merge: expand range, preserve stronger title
                    merged_start = min(section.start_block_idx, dedup_section.start_block_idx)
                    merged_end = max(section.end_block_idx, dedup_section.end_block_idx)

                    # Choose the more specific/longer title
                    merged_title = section.title or dedup_section.title
                    if dedup_section.title and (not section.title or len(str(dedup_section.title)) > len(str(section.title))):
                        merged_title = dedup_section.title

                    # Create merged section
                    merged_section = DetectedSection(
                        section_id=f"semantic_{str(uuid4())}",
                        start_block_idx=merged_start,
                        end_block_idx=merged_end,
                        title=merged_title,
                        heading_level=section.heading_level or dedup_section.heading_level,
                        block_count=merged_end - merged_start + 1,
                        paragraph_count=section.paragraph_count + dedup_section.paragraph_count,
                        table_count=section.table_count + dedup_section.table_count,
                        content_length=section.content_length + dedup_section.content_length,
                        boundary_marker=section.boundary_marker or dedup_section.boundary_marker,
                    )

                    # Replace the deduplicated section with merged version
                    deduplicated[j] = merged_section
                    merged_flag = True
                    break

        if not merged_flag:
            # No merge needed, add as new deduplicated section
            deduplicated.append(section)

    # Final sort by start block index
    deduplicated.sort(key=lambda s: s.start_block_idx)
    return deduplicated
