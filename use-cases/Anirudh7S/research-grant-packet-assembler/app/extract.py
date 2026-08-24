import re
from typing import Any, Dict, List


def clean_text(text: str) -> str:
    """Normalize whitespace without changing the actual wording."""
    return re.sub(r"\s+", " ", text).strip()


def extract_labeled_section(
    content: str,
    start_label: str,
    end_labels: List[str],
) -> str:
    """Extract text between one section heading and the next known heading."""

    if end_labels:
        escaped_end_labels = "|".join(
            re.escape(label) for label in end_labels
        )

        pattern = (
            re.escape(start_label)
            + r"\s*(.*?)(?=\n(?:"
            + escaped_end_labels
            + r")\s*\n|\Z)"
        )
    else:
        pattern = re.escape(start_label) + r"\s*(.*)\Z"

    match = re.search(
        pattern,
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return ""

    return clean_text(match.group(1))


def extract_labeled_lines(
    content: str,
    start_label: str,
    end_labels: List[str],
) -> List[str]:
    """Extract a section while preserving individual lines."""

    lines = content.splitlines()
    collecting = False
    result = []

    normalized_end_labels = {
        label.strip().lower()
        for label in end_labels
    }

    for line in lines:
        stripped = line.strip()

        if stripped.lower() == start_label.strip().lower():
            collecting = True
            continue

        if collecting and stripped.lower() in normalized_end_labels:
            break

        if collecting and stripped:
            result.append(clean_text(stripped))

    return result


def extract_labeled_lines_aliases(
    content: str,
    start_labels: List[str],
    end_labels: List[str],
) -> List[str]:
    """Extract lines from a section supporting multiple heading aliases."""

    lines = content.splitlines()
    collecting = False
    result = []

    normalized_starts = {
        label.strip().lower()
        for label in start_labels
    }

    normalized_ends = {
        label.strip().lower()
        for label in end_labels
    }

    for line in lines:
        stripped = line.strip()
        normalized = stripped.lower()

        if normalized in normalized_starts:
            collecting = True
            continue

        if collecting and normalized in normalized_ends:
            break

        if collecting and stripped:
            result.append(clean_text(stripped))

    return result


def extract_research_narrative(content: str) -> Dict[str, Any]:
    """Extract structured facts from a research narrative."""

    facts: Dict[str, Any] = {
        "project_title": "",
        "principal_investigator": "",
        "co_investigator": "",
        "project_summary": "",
        "specific_aims": [],
        "research_approach": "",
        "expected_outcomes": "",
        "significance": "",
    }

    # Project title
    match = re.search(
        r"Project Title:\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["project_title"] = clean_text(match.group(1))

    # Principal Investigator
    match = re.search(
        r"Principal Investigator:\s*\n\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["principal_investigator"] = clean_text(match.group(1))

    # Co-Investigator
    match = re.search(
        r"Co-Investigator:\s*\n\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["co_investigator"] = clean_text(match.group(1))

    section_labels = [
        "Project Summary",
        "Specific Aim 1",
        "Specific Aim 2",
        "Specific Aim 3",
        "Research Approach",
        "Expected Outcomes",
        "Significance",
        "Investigators",
    ]

    facts["project_summary"] = extract_labeled_section(
        content,
        "Project Summary",
        section_labels[1:],
    )

    aim_1 = extract_labeled_section(
        content,
        "Specific Aim 1",
        section_labels[2:],
    )

    aim_2 = extract_labeled_section(
        content,
        "Specific Aim 2",
        section_labels[3:],
    )

    aim_3 = extract_labeled_section(
        content,
        "Specific Aim 3",
        section_labels[4:],
    )

    facts["specific_aims"] = [
        aim
        for aim in [aim_1, aim_2, aim_3]
        if aim
    ]

    facts["research_approach"] = extract_labeled_section(
        content,
        "Research Approach",
        section_labels[5:],
    )

    facts["expected_outcomes"] = extract_labeled_section(
        content,
        "Expected Outcomes",
        section_labels[6:],
    )

    facts["significance"] = extract_labeled_section(
        content,
        "Significance",
        section_labels[7:],
    )

    return facts


def extract_data_management_plan(content: str) -> Dict[str, Any]:
    """Extract structured facts from a data management plan."""

    facts: Dict[str, Any] = {
        "project": "",
        "principal_investigator": "",
        "co_investigator": "",
        "data_types": "",
        "data_collection": "",
        "data_storage": "",
        "data_security": "",
        "data_quality": "",
        "data_sharing": "",
        "data_retention": "",
    }

    match = re.search(
        r"Project:\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["project"] = clean_text(match.group(1))

    match = re.search(
        r"Principal Investigator:\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["principal_investigator"] = clean_text(match.group(1))

    match = re.search(
        r"Co-Investigator:\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["co_investigator"] = clean_text(match.group(1))

    section_labels = [
        "Data Types",
        "Data Collection",
        "Data Storage",
        "Data Security",
        "Data Quality",
        "Data Sharing",
        "Data Retention",
    ]

    for index, section in enumerate(section_labels):
        end_labels = section_labels[index + 1:]

        facts_key = section.lower().replace(" ", "_")

        facts[facts_key] = extract_labeled_section(
            content,
            section,
            end_labels,
        )

    return facts


def extract_investigator_cv(content: str) -> Dict[str, Any]:
    """Extract structured facts from different investigator CV formats."""

    facts: Dict[str, Any] = {
        "name": "",
        "current_position": "",
        "education": [],
        "research_interests": [],
        "professional_experience": [],
        "selected_publications": [],
        "awards": [],
        "current_grant_role": "",
    }

    lines = [
        line.strip()
        for line in content.splitlines()
        if line.strip()
    ]

    # The investigator name is normally the second non-empty line.
    if len(lines) >= 2:
        facts["name"] = lines[1]

    # Supported heading aliases
    current_position_labels = [
        "Current Position",
        "Professional Role",
    ]

    education_labels = [
        "Education",
        "Academic Training",
    ]

    research_labels = [
        "Research Interests",
        "Research Focus",
    ]

    experience_labels = [
        "Professional Experience",
        "Employment History",
    ]

    publication_labels = [
        "Selected Publications",
        "Selected Research",
    ]

    award_labels = [
        "Awards",
        "Honors",
    ]

    grant_role_labels = [
        "Current Grant Role",
        "Grant Responsibility",
    ]

    all_section_labels = (
        current_position_labels
        + education_labels
        + research_labels
        + experience_labels
        + publication_labels
        + award_labels
        + grant_role_labels
    )

    # Current position / professional role
    facts["current_position"] = ""

    for label in current_position_labels:
        facts["current_position"] = extract_labeled_section(
            content,
            label,
            [x for x in all_section_labels if x not in current_position_labels],
        )

        if facts["current_position"]:
            break

    # Education / academic training
    facts["education"] = extract_labeled_lines_aliases(
        content,
        education_labels,
        [
            x
            for x in all_section_labels
            if x not in education_labels
        ],
    )

    # Research interests / research focus
    facts["research_interests"] = extract_labeled_lines_aliases(
        content,
        research_labels,
        [
            x
            for x in all_section_labels
            if x not in research_labels
        ],
    )

    # Professional experience / employment history
    facts["professional_experience"] = extract_labeled_lines_aliases(
        content,
        experience_labels,
        [
            x
            for x in all_section_labels
            if x not in experience_labels
        ],
    )

    # Selected publications / selected research
    facts["selected_publications"] = extract_labeled_lines_aliases(
        content,
        publication_labels,
        [
            x
            for x in all_section_labels
            if x not in publication_labels
        ],
    )

    # Awards / honors
    facts["awards"] = extract_labeled_lines_aliases(
        content,
        award_labels,
        [
            x
            for x in all_section_labels
            if x not in award_labels
        ],
    )

    # Current grant role / grant responsibility
    facts["current_grant_role"] = ""

    for label in grant_role_labels:
        facts["current_grant_role"] = extract_labeled_section(
            content,
            label,
            [],
        )

        if facts["current_grant_role"]:
            break

    return facts

def extract_facilities_statement(content: str) -> Dict[str, Any]:
    """Extract structured facts from a facilities statement."""

    facts: Dict[str, Any] = {
        "project": "",
        "facilities_and_sites": "",
        "space_and_screening": "",
        "data_systems": "",
        "institutional_support": "",
        "investigator_responsibilities": "",
    }

    # Project
    match = re.search(
        r"Project:\s*(.+)",
        content,
        flags=re.IGNORECASE,
    )

    if match:
        facts["project"] = clean_text(match.group(1))

    # Split the document into paragraphs.
    paragraphs = [
        clean_text(paragraph)
        for paragraph in re.split(r"\n\s*\n", content)
        if clean_text(paragraph)
    ]

    # Expected structure:
    # 0 = FACILITIES STATEMENT
    # 1 = Project: ...
    # 2 = Facilities/sites paragraph
    # 3 = Space/screening + data systems paragraph
    # 4 = Institutional support paragraph
    # 5 = Investigator responsibilities paragraph

    if len(paragraphs) >= 3:
        facts["facilities_and_sites"] = paragraphs[2]

    if len(paragraphs) >= 4:
        facts["space_and_screening"] = paragraphs[3]

    if len(paragraphs) >= 5:
        facts["institutional_support"] = paragraphs[4]

    if len(paragraphs) >= 6:
        facts["investigator_responsibilities"] = paragraphs[5]

    # Extract the data-system statement from the
    # space/screening paragraph.
    if facts["space_and_screening"]:
        data_match = re.search(
            r"The research team will use secure project systems for data collection and storage\.",
            facts["space_and_screening"],
            flags=re.IGNORECASE,
        )

        if data_match:
            facts["data_systems"] = clean_text(
                data_match.group(0)
            )

    return facts

def extract_budget_justification(content: str) -> Dict[str, Any]:
    """Extract structured facts from a budget justification."""

    facts: Dict[str, Any] = {
        "personnel": "",
        "principal_investigator": "",
        "co_investigator": "",
        "participant_and_site_activities": "",
        "data_management": "",
        "dissemination": "",
    }

    section_map = {
        "Personnel": "personnel",
        "Principal Investigator": "principal_investigator",
        "Co-Investigator": "co_investigator",
        "Participant and Site Activities": "participant_and_site_activities",
        "Data Management": "data_management",
        "Dissemination": "dissemination",
    }

    section_labels = list(section_map.keys())

    for index, section in enumerate(section_labels):
        end_labels = section_labels[index + 1:]

        facts_key = section_map[section]

        facts[facts_key] = extract_labeled_section(
            content,
            section,
            end_labels,
        )

    return facts