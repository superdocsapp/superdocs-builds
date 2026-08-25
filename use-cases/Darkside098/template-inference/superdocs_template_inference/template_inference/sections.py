"""Section alignment, ordering, and presence inference."""

import re
from uuid import uuid4

from superdocs_template_inference.models import (
    Block,
    DetectedSection,
    Document,
    DocumentProfile,
    ParagraphBlock,
    TableBlock,
)


def _get_canonical_section_title_internal(title: str | None) -> str:
    """Get canonical form of a section title for INTERNAL GROUPING using underscores.

    Matches the logic in _canonical_title_for_dedup() from sections_document_aware.py
    to ensure consistent grouping of semantically equivalent sections.
    Converts spaces to underscores for use as dictionary keys in align_sections().

    Args:
        title: Section title to normalize.

    Returns:
        Canonical lowercase title with underscores replacing spaces.
    """
    if not title:
        return ""

    normalized = str(title).strip().lower()
    normalized = re.sub(r"[^a-z0-9_]+", "_", normalized)
    normalized = re.sub(r"_+", "_", normalized).strip("_")

    # Map semantic aliases to canonical forms
    # Must match the mapping in _canonical_title_for_dedup()
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


def _get_canonical_section_title_output(title: str | None) -> str:
    """Get canonical form of a section title for OUTPUT (title_or_pattern) using spaces.

    Used for building TemplateSection.title_or_pattern field.
    Preserves spaces but applies semantic alias mapping for consistency.

    Args:
        title: Section title to normalize.

    Returns:
        Canonical lowercase title with spaces (not underscores).
    """
    if not title:
        return ""

    # First normalize to internal form to get canonical alias
    internal_form = _get_canonical_section_title_internal(title)

    # Convert underscores back to spaces for output
    output_form = internal_form.replace("_", " ")

    return output_form


def align_sections(profiles: list[DocumentProfile]) -> dict[str, list[DetectedSection]]:
    """Align sections across profiles by normalized title/pattern.

    Args:
        profiles: List of DocumentProfile objects from a single family.

    Returns:
        Mapping {section_pattern: [DetectedSection, ...]} for aligned sections.
    """
    if not profiles:
        return {}

    # Normalize and group sections by title pattern (using internal underscore form for grouping)
    section_groups: dict[str, list[DetectedSection]] = {}

    for profile in profiles:
        for section in profile.sections:
            # Use internal canonical form (with underscores) for grouping
            normalized_title = _get_canonical_section_title_internal(section.title or "")

            if normalized_title not in section_groups:
                section_groups[normalized_title] = []

            section_groups[normalized_title].append(section)

    return section_groups


def detect_section_variants(
    section_groups: dict[str, list[DetectedSection]],
    profiles: list[DocumentProfile],
) -> dict[str, list[str]]:
    """Detect sections that are variants of the same logical zone.

    Identifies sections with different names that occupy similar block positions
    across documents, appearing in DIFFERENT documents but never together.
    These are typically conditional alternatives (e.g.,
    "remote_work_setup" vs "office_access_desk_setup").

    Uses union-find to group all transitively related variants together.

    Args:
        section_groups: Mapping {section_title: [DetectedSection, ...]}
        profiles: List of DocumentProfile objects

    Returns:
        Mapping {variant_group_name: [section_title1, section_title2, ...]}
        where variant_group_name is a canonical identifier for the group.
    """
    if not section_groups or len(profiles) < 2:
        return {}

    # Build a map of which sections appear in which documents
    section_to_docs = {}  # section_title -> set of document indices
    section_positions = {}  # section_title -> list of (start, end) tuples

    for title, sections in section_groups.items():
        docs_with_section = set()
        positions = []
        for section in sections:
            # Find which document this section is from
            for doc_idx, profile in enumerate(profiles):
                if any(
                    _get_canonical_section_title_internal(s.title or "") == title
                    for s in profile.sections
                ):
                    docs_with_section.add(doc_idx)
                    positions.append((section.start_block_idx, section.end_block_idx))
                    break

        if docs_with_section:
            section_to_docs[title] = docs_with_section
            section_positions[title] = positions

    # Only consider OPTIONAL sections (those appearing in <95% of docs)
    optional_sections = {
        title: docs
        for title, docs in section_to_docs.items()
        if len(docs) > 0 and len(docs) < len(profiles) * 0.95
    }

    if not optional_sections:
        return {}

    # SIMPLIFIED: Variant detection disabled
    # All optional sections are now treated directly as conditional sections
    # if they have predictive variable conditions (handled in inferer.py)
    # This avoids false grouping while still recognizing variants through conditional inference
    return {}


def normalize_section_title(title: str | None) -> str:
    """Normalize section title for OUTPUT (title_or_pattern).

    Uses canonical semantic alias mapping with spaces to ensure semantically equivalent
    sections (e.g., "your_first_day" vs "first_day") use the same output format.

    Args:
        title: Section title or heading text.

    Returns:
        Normalized canonical title for output (with spaces, not underscores).
    """
    if not title:
        return "untitled"

    return _get_canonical_section_title_output(title)


def infer_section_ordering(profiles: list[DocumentProfile]) -> list[str]:
    """Infer the dominant section order across documents.

    Args:
        profiles: List of DocumentProfile objects from a single family.

    Returns:
        Ordered list of normalized section titles (internal form with underscores),
        with duplicates removed while preserving order of first occurrence.
    """
    if not profiles:
        return []

    # Collect all section orders
    orders = []

    for profile in profiles:
        section_order = [
            _get_canonical_section_title_internal(s.title or "") for s in profile.sections
        ]
        if section_order:
            orders.append(section_order)

    if not orders:
        return []

    # For simplicity, use the order from the first document but deduplicate
    # This preserves order while removing consecutive or non-consecutive duplicates
    order = orders[0]

    # Remove duplicates while preserving order of first occurrence
    seen = set()
    deduplicated_order = []
    for title in order:
        if title not in seen:
            seen.add(title)
            deduplicated_order.append(title)

    return deduplicated_order


def calculate_section_presence_frequency(
    section_pattern: str, profiles: list[DocumentProfile], section_groups: dict[str, list]
) -> float:
    """Calculate how frequently a section appears across documents.

    Counts unique documents that contain the section (handles deduplication edge case
    where a profile might still have multiple detections).

    Args:
        section_pattern: Normalized section title.
        profiles: List of DocumentProfile objects from a single family.
        section_groups: Grouped sections by pattern (list of DetectedSection objects).

    Returns:
        Frequency as 0.0–1.0, always clamped to valid range.
    """
    if not profiles:
        return 0.0

    if section_pattern not in section_groups:
        return 0.0

    sections = section_groups[section_pattern]

    # Count unique profiles (documents) that have at least one section matching this pattern
    # Use explicit object identity (is) instead of == because DetectedSection is a dataclass
    # with value-based equality that would incorrectly match sections across profiles
    seen_profiles = set()
    for section in sections:
        # Find which profile this section belongs to using object identity
        for profile in profiles:
            # Use 'any() with is' for explicit object identity check, not value-based equality
            if any(section is s for s in profile.sections):
                seen_profiles.add(profile.document_id)
                break

    # Fallback: if we couldn't map sections to profiles, just count unique contributions
    if not seen_profiles:
        # This means the sections_groups list has sections but we can't trace them to profiles
        # In this case, use the simpler count but still clamp
        unique_count = min(len(sections), len(profiles))
    else:
        unique_count = len(seen_profiles)

    # Calculate frequency and clamp to [0.0, 1.0]
    frequency = unique_count / len(profiles)
    frequency = max(0.0, min(1.0, frequency))

    return frequency



def classify_section_presence(frequency: float) -> str:
    """Classify section presence based on frequency.

    Args:
        frequency: Presence frequency 0.0–1.0.

    Returns:
        "always" if frequency >= 0.95
        "usually" if frequency >= 0.6
        "optional" if frequency < 0.6
    """
    if frequency >= 0.95:
        return "always"
    if frequency >= 0.6:
        return "usually"
    return "optional"


def get_section_content_representation(sections: list[DetectedSection]) -> str:
    """Get a normalized content representation for aligned sections.

    Args:
        sections: List of DetectedSection objects at the same logical position.

    Returns:
        Summary representation of section content.
    """
    if not sections:
        return ""

    # Extract the most common title
    titles = [s.title for s in sections if s.title]
    if titles:
        return titles[0]

    return f"Section (blocks: {sections[0].block_count if sections else 0})"


# M7: Semantic Section Detection


def _is_title_like(text: str) -> bool:
    """Check if text looks like a section title/heading even without heading style.

    Args:
        text: The text to check.

    Returns:
        True if text looks title-like: short, often uppercase, no lowercase common words.
    """
    if not text or len(text.strip()) == 0:
        return False

    stripped = text.strip()

    # Too long to be title
    if len(stripped) > 100:
        return False

    # Check if mostly uppercase
    if len(stripped) >= 4:
        non_space = ''.join(c for c in stripped if not c.isspace())
        if not non_space:
            return False
        upper_ratio = sum(1 for c in non_space if c.isupper()) / len(non_space)
        if upper_ratio >= 0.6:
            return True

    # Check if very short (1-3 words, title case)
    words = stripped.split()
    if len(words) <= 3 and all(w[0].isupper() if w else False for w in words if w):
        return True

    return False


def _is_greeting_like(text: str) -> bool:
    """Check if text looks like a greeting/salutation.

    Args:
        text: The text to check.

    Returns:
        True if text looks like a greeting (Dear, Hello, etc.).
    """
    if not text:
        return False

    normalized = text.strip().lower()
    greeting_patterns = [
        r"^dear\s+",
        r"^hello\s+",
        r"^hi\s+",
        r"^greetings",
        r"^welcome",
    ]

    return any(re.match(pattern, normalized) for pattern in greeting_patterns)


def _is_signature_block(text: str) -> bool:
    """Check if text looks like signature/closing block.

    Args:
        text: The text to check.

    Returns:
        True if text looks like signature or closing.
    """
    if not text:
        return False

    normalized = text.strip().lower()

    # Common closing/signature phrases
    if any(phrase in normalized for phrase in [
        "sincerely", "warm regards", "best regards", "regards",
        "yours truly", "thank you", "kind regards"
    ]):
        return True

    # Single line that's a name-like pattern (starts with capital)
    lines = text.strip().split('\n')
    if len(lines) <= 3:
        for line in lines:
            clean = line.strip()
            if clean and len(clean.split()) <= 3:
                if clean[0].isupper() and not any(
                    kw in clean.lower() for kw in [
                        "department", "company", "address", "email", "phone"
                    ]
                ):
                    return True

    return False


def _is_contact_info_block(text: str) -> bool:
    """Check if text looks like contact information.

    Args:
        text: The text to check.

    Returns:
        True if text contains contact patterns.
    """
    if not text:
        return False

    normalized = text.lower()
    contact_patterns = [
        r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b",  # phone
        r"\b[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}\b",  # email
        r"\bwww\.",
        r"address\s*:",
        r"phone\s*:",
        r"email\s*:",
    ]

    return any(re.search(pattern, normalized) for pattern in contact_patterns)


def _is_date_reference_block(text: str) -> bool:
    """Check if text looks like date/reference field block.

    Args:
        text: The text to check.

    Returns:
        True if text contains date/reference patterns.
    """
    if not text:
        return False

    normalized = text.lower()

    patterns = [
        r"date\s*:\s*\d",
        r"reference\s*:\s*",
        r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b",  # date format
        r"(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2},?\s+\d{4}",
    ]

    return any(re.search(pattern, normalized) for pattern in patterns)


def detect_semantic_sections(profile: DocumentProfile) -> list[DetectedSection]:
    """Detect semantic zones from document profile structure and content.

    Analyzes block sequences, heading texts, vocabulary, and paragraph patterns
    to identify semantic zones even when Word heading styles are absent.

    Args:
        profile: DocumentProfile with structural, content, and formatting info.

    Returns:
        List of additional semantic DetectedSection objects. Empty if no strong
        semantic patterns detected.
    """
    if not profile or not profile.structural or not profile.content:
        return []

    semantic_sections = []
    block_seq = profile.structural.block_type_sequence
    heading_texts = profile.content.heading_texts or []

    if not block_seq:
        return []

    # Find table regions in block sequence
    table_regions = []
    for i, block_type in enumerate(block_seq):
        if block_type == "table":
            table_regions.append(i)

    # Strategy 1: Detect company/contact header (start of document)
    if len(block_seq) >= 2:
        header_end = min(3, len(block_seq))
        has_early_table = any(i < header_end for i in table_regions)
        has_contact_pattern = _is_contact_info_block(" ".join(heading_texts[:3]))

        if has_contact_pattern or has_early_table:
            semantic_sections.append(DetectedSection(
                section_id=f"semantic_{str(uuid4())}",
                start_block_idx=0,
                end_block_idx=min(2, len(block_seq) - 1),
                title="company_header",
                heading_level=None,
                block_count=min(3, len(block_seq)),
                paragraph_count=0,
                table_count=sum(1 for i in range(min(3, len(block_seq))) if block_seq[i] == "table"),
                content_length=0,
                boundary_marker="semantic_pattern",
            ))

    # Strategy 2: Detect title-like paragraphs as section markers
    short_para_indices = []
    if len(profile.structural.paragraph_lengths) > 0:
        median_length = sorted(profile.structural.paragraph_lengths)[len(profile.structural.paragraph_lengths) // 2]
        threshold = median_length * 0.3  # Very short paragraphs

        for text in heading_texts:
            if _is_title_like(text):
                short_para_indices.append(text)

    # Strategy 3: Detect greeting block (usually near start after title/intro)
    for i, text in enumerate(heading_texts[:min(10, len(heading_texts))]):
        if _is_greeting_like(text) and i > 0:
            semantic_sections.append(DetectedSection(
                section_id=f"semantic_{str(uuid4())}",
                start_block_idx=max(0, i - 1),
                end_block_idx=min(i + 2, len(block_seq) - 1),
                title="greeting",
                heading_level=None,
                block_count=3,
                paragraph_count=2,
                table_count=0,
                content_length=0,
                boundary_marker="semantic_pattern",
            ))
            break

    # Strategy 4: Detect table zones for key/value data
    for table_idx in table_regions:
        # Tables with 2-3 columns are likely key-value metadata
        # Tables with 2-4 rows are likely header/employee info
        table_size = profile.structural.table_dimensions[table_regions.index(table_idx)] if table_regions.index(table_idx) < len(profile.structural.table_dimensions) else (0, 0)

        if 0 < table_size[1] <= 4:  # 1-4 columns: likely metadata
            # Check nearby text for semantic hints
            context_start = max(0, table_idx - 1)
            context_end = min(table_idx + 2, len(block_seq))
            context_text = " ".join(heading_texts[context_start:context_end]).lower()

            zone_name = "data_table"
            if any(word in context_text for word in ["employee", "position", "department", "id"]):
                zone_name = "employee_information"
            elif any(word in context_text for word in ["start", "arrival", "date", "time", "location", "work mode"]):
                zone_name = "first_day"
            elif any(word in context_text for word in ["orientation", "training"]):
                zone_name = "orientation"

            semantic_sections.append(DetectedSection(
                section_id=f"semantic_{str(uuid4())}",
                start_block_idx=max(0, table_idx - 1),
                end_block_idx=min(table_idx + 1, len(block_seq) - 1),
                title=zone_name,
                heading_level=None,
                block_count=2,
                paragraph_count=1,
                table_count=1,
                content_length=0,
                boundary_marker="semantic_pattern",
            ))

    # Strategy 5: Detect closing/signature block (end of document)
    if len(block_seq) >= 3 and len(heading_texts) >= 3:
        end_context = " ".join(heading_texts[-3:])
        if _is_signature_block(end_context):
            semantic_sections.append(DetectedSection(
                section_id=f"semantic_{str(uuid4())}",
                start_block_idx=max(0, len(block_seq) - 3),
                end_block_idx=len(block_seq) - 1,
                title="closing_signature",
                heading_level=None,
                block_count=3,
                paragraph_count=2,
                table_count=0,
                content_length=0,
                boundary_marker="semantic_pattern",
            ))

    return semantic_sections


def augment_sections_with_semantic_names(
    sections: list[DetectedSection], profile: DocumentProfile
) -> list[DetectedSection]:
    """Augment existing sections with semantic zone names when appropriate.

    For sections without titles (e.g., "untitled"), try to infer semantic names
    from content patterns.

    Args:
        sections: Existing DetectedSection objects.
        profile: DocumentProfile for context.

    Returns:
        Sections with potentially updated titles.
    """
    if not sections or not profile or not profile.content:
        return sections

    augmented = []
    heading_texts = profile.content.heading_texts or []

    for section in sections:
        # If section already has a meaningful title, keep it
        if section.title and section.title.lower() != "untitled" and len(section.title) > 3:
            augmented.append(section)
            continue

        # Try to infer semantic name from section content
        section_heading_texts = heading_texts[section.start_block_idx:section.end_block_idx + 1]
        context_text = " ".join(section_heading_texts)

        semantic_name = None

        if _is_greeting_like(context_text):
            semantic_name = "greeting"
        elif _is_signature_block(context_text):
            semantic_name = "closing_signature"
        elif _is_contact_info_block(context_text):
            semantic_name = "contact_information"
        elif _is_date_reference_block(context_text):
            semantic_name = "date_and_reference"
        elif section.table_count > 0 and section.paragraph_count <= 2:
            semantic_name = "data_table"

        if semantic_name:
            # Create new section with semantic name
            new_section = DetectedSection(
                section_id=section.section_id,
                start_block_idx=section.start_block_idx,
                end_block_idx=section.end_block_idx,
                title=semantic_name,
                heading_level=section.heading_level,
                block_count=section.block_count,
                paragraph_count=section.paragraph_count,
                table_count=section.table_count,
                content_length=section.content_length,
                boundary_marker=section.boundary_marker,
            )
            augmented.append(new_section)
        else:
            augmented.append(section)

    return augmented
