from typing import Any, Dict, List


BIOSKETCH_SECTIONS = [
    "Personal Information",
    "Current Position",
    "Education and Training",
    "Research Interests",
    "Professional Experience",
    "Selected Publications",
    "Awards and Honors",
    "Current Grant Role",
]


def _clean_list(values: List[str]) -> List[str]:
    """Return non-empty, normalized list values."""
    return [
        str(value).strip()
        for value in values
        if str(value).strip()
    ]


def build_funder_biosketch(
    investigator_facts: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Convert normalized investigator CV facts into a funder-style
    biosketch without dropping extracted content.
    """

    name = str(
        investigator_facts.get("name", "")
    ).strip()

    current_position = str(
        investigator_facts.get("current_position", "")
    ).strip()

    education = _clean_list(
        investigator_facts.get("education", [])
    )

    research_interests = _clean_list(
        investigator_facts.get("research_interests", [])
    )

    professional_experience = _clean_list(
        investigator_facts.get("professional_experience", [])
    )

    selected_publications = _clean_list(
        investigator_facts.get("selected_publications", [])
    )

    awards = _clean_list(
        investigator_facts.get("awards", [])
    )

    current_grant_role = str(
        investigator_facts.get("current_grant_role", "")
    ).strip()

    return {
        "name": name,
        "sections": {
            "Personal Information": {
                "name": name,
            },
            "Current Position": {
                "content": current_position,
            },
            "Education and Training": {
                "items": education,
            },
            "Research Interests": {
                "items": research_interests,
            },
            "Professional Experience": {
                "items": professional_experience,
            },
            "Selected Publications": {
                "items": selected_publications,
            },
            "Awards and Honors": {
                "items": awards,
            },
            "Current Grant Role": {
                "content": current_grant_role,
            },
        },
    }


def render_funder_biosketch(
    biosketch: Dict[str, Any],
) -> str:
    """Render a structured biosketch as readable text."""

    sections = biosketch.get("sections", {})

    lines: List[str] = []

    name = sections.get(
        "Personal Information",
        {},
    ).get("name", "")

    if name:
        lines.append(name)
        lines.append("")

    for section_name in BIOSKETCH_SECTIONS[1:]:
        section = sections.get(
            section_name,
            {},
        )

        lines.append(section_name)

        content = section.get("content", "")

        if content:
            lines.append(content)

        for item in section.get("items", []):
            lines.append(f"- {item}")

        lines.append("")

    return "\n".join(lines).strip()


def compare_source_content(
    investigator_facts: Dict[str, Any],
    biosketch: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Verify that every extracted CV fact is represented in the
    generated biosketch.

    This is a preservation check, not a semantic similarity score.
    """

    source_fields = {
        "name": investigator_facts.get("name", ""),
        "current_position": investigator_facts.get(
            "current_position",
            "",
        ),
        "education": investigator_facts.get(
            "education",
            [],
        ),
        "research_interests": investigator_facts.get(
            "research_interests",
            [],
        ),
        "professional_experience": investigator_facts.get(
            "professional_experience",
            [],
        ),
        "selected_publications": investigator_facts.get(
            "selected_publications",
            [],
        ),
        "awards": investigator_facts.get(
            "awards",
            [],
        ),
        "current_grant_role": investigator_facts.get(
            "current_grant_role",
            "",
        ),
    }

    rendered = render_funder_biosketch(
        biosketch
    ).lower()

    missing: List[str] = []

    for field, values in source_fields.items():
        if isinstance(values, list):
            for value in values:
                value = str(value).strip()

                if value and value.lower() not in rendered:
                    missing.append(
                        f"{field}: {value}"
                    )

        else:
            value = str(values).strip()

            if value and value.lower() not in rendered:
                missing.append(
                    f"{field}: {value}"
                )

    return {
        "preserved": len(missing) == 0,
        "missing_content": missing,
        "source_fields_checked": len(
            [
                value
                for value in source_fields.values()
                if value
            ]
        ),
    }


def convert_investigator_to_biosketch(
    investigator_facts: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Complete CV-to-biosketch conversion with a content-preservation
    check.
    """

    biosketch = build_funder_biosketch(
        investigator_facts
    )

    preservation = compare_source_content(
        investigator_facts,
        biosketch,
    )

    return {
        "name": investigator_facts.get(
            "name",
            "",
        ),
        "format": "funder_biosketch",
        "biosketch": biosketch,
        "rendered_text": render_funder_biosketch(
            biosketch
        ),
        "content_preservation": preservation,
    }