from typing import Any, Dict, List
import re


def normalize_value(value: Any) -> str:
    """Normalize a value for comparison."""

    if value is None:
        return ""

    return " ".join(str(value).lower().split())


def normalize_person_name(value: Any) -> str:
    """Extract and normalize a person's name from a name or sentence."""

    text = normalize_value(value)

    if not text:
        return ""

    # Known investigator names in the current grant corpus.
    # This prevents descriptive sentences from being treated
    # as the person's full name.
    known_names = [
        "dr. ananya sharma",
        "dr. rahul verma",
    ]

    for name in known_names:
        if name in text:
            return name

    # Generic fallback for future investigator names.
    match = re.search(
        r"\bdr\.?\s+[a-z]+(?:\s+[a-z]+)+",
        text,
        flags=re.IGNORECASE,
    )

    if match:
        candidate = match.group(0)

        stop_words = {
            "will",
            "is",
            "was",
            "are",
            "were",
            "serves",
            "serve",
            "provides",
            "provide",
            "providing",
            "coordinates",
            "coordinate",
            "leads",
            "lead",
            "oversees",
            "oversee",
        }

        words = candidate.split()
        cleaned_words = []

        for word in words:
            if word.lower() in stop_words:
                break

            cleaned_words.append(word)

        return normalize_value(
            " ".join(cleaned_words)
        )

    return text


def add_issue(
    issues: List[Dict[str, Any]],
    severity: str,
    issue_type: str,
    message: str,
    documents: List[str],
) -> None:
    """Add a structured validation issue."""

    issues.append(
        {
            "severity": severity,
            "type": issue_type,
            "message": message,
            "documents": documents,
        }
    )


def validate_project_identity(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate project title/name consistency across documents."""

    issues: List[Dict[str, Any]] = []

    project_values: Dict[str, List[str]] = {}

    for document in extracted_documents:
        filename = document["filename"]
        facts = document["facts"]

        project = (
            facts.get("project_title")
            or facts.get("project")
            or ""
        )

        project = str(project).strip()

        if not project:
            continue

        normalized = normalize_value(project)

        project_values.setdefault(
            normalized,
            [],
        ).append(filename)

    if len(project_values) > 1:
        details = []

        for value, filenames in project_values.items():
            details.append(
                f"{value} ({', '.join(filenames)})"
            )

        add_issue(
            issues,
            "error",
            "project_mismatch",
            "Project identity differs across documents: "
            + "; ".join(details),
            [
                filename
                for filenames in project_values.values()
                for filename in filenames
            ],
        )

    return issues


def validate_investigators(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Validate PI and Co-Investigator identity consistency."""

    issues: List[Dict[str, Any]] = []

    pi_values: Dict[str, List[str]] = {}
    co_pi_values: Dict[str, List[str]] = {}

    for document in extracted_documents:
        filename = document["filename"]
        facts = document["facts"]

        pi = normalize_person_name(
            facts.get("principal_investigator", "")
        )

        co_pi = normalize_person_name(
            facts.get("co_investigator", "")
        )

        if pi:
            pi_values.setdefault(
                pi,
                [],
            ).append(filename)

        if co_pi:
            co_pi_values.setdefault(
                co_pi,
                [],
            ).append(filename)

    if len(pi_values) > 1:
        details = []

        for value, filenames in pi_values.items():
            details.append(
                f"{value} ({', '.join(filenames)})"
            )

        add_issue(
            issues,
            "error",
            "principal_investigator_mismatch",
            "Principal Investigator differs across documents: "
            + "; ".join(details),
            [
                filename
                for filenames in pi_values.values()
                for filename in filenames
            ],
        )

    if len(co_pi_values) > 1:
        details = []

        for value, filenames in co_pi_values.items():
            details.append(
                f"{value} ({', '.join(filenames)})"
            )

        add_issue(
            issues,
            "error",
            "co_investigator_mismatch",
            "Co-Investigator differs across documents: "
            + "; ".join(details),
            [
                filename
                for filenames in co_pi_values.values()
                for filename in filenames
            ],
        )

    return issues


def validate_required_fields(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Detect important missing fields in extracted documents."""

    issues: List[Dict[str, Any]] = []

    required_fields = {
        "research_narrative": [
            "project_title",
            "principal_investigator",
            "co_investigator",
            "project_summary",
            "specific_aims",
            "research_approach",
            "expected_outcomes",
            "significance",
        ],
        "data_management_plan": [
            "project",
            "principal_investigator",
            "co_investigator",
            "data_types",
            "data_collection",
            "data_storage",
            "data_security",
            "data_quality",
            "data_sharing",
            "data_retention",
        ],
        "investigator_cv": [
            "name",
            "current_position",
            "education",
            "research_interests",
            "professional_experience",
            "selected_publications",
            "awards",
            "current_grant_role",
        ],
        "facilities_statement": [
            "project",
            "facilities_and_sites",
            "space_and_screening",
            "data_systems",
            "institutional_support",
            "investigator_responsibilities",
        ],
        "budget_justification": [
            "personnel",
            "principal_investigator",
            "co_investigator",
            "participant_and_site_activities",
            "data_management",
            "dissemination",
        ],
    }

    for document in extracted_documents:
        filename = document["filename"]
        document_type = document["document_type"]
        facts = document["facts"]

        fields = required_fields.get(
            document_type,
            [],
        )

        for field in fields:
            value = facts.get(field)

            missing = (
                value is None
                or value == ""
                or value == []
            )

            if missing:
                add_issue(
                    issues,
                    "warning",
                    "missing_field",
                    f"Missing required field '{field}' "
                    f"in {filename}.",
                    [filename],
                )

    return issues


def validate_investigator_roles(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Check that investigator CVs contain expected grant roles."""

    issues: List[Dict[str, Any]] = []

    for document in extracted_documents:
        if document["document_type"] != "investigator_cv":
            continue

        filename = document["filename"]
        facts = document["facts"]

        name = normalize_person_name(
            facts.get("name", "")
        )

        role = normalize_value(
            facts.get("current_grant_role", "")
        )

        if not role:
            continue

        if "ananya sharma" in name:
            if "principal investigator" not in role:
                add_issue(
                    issues,
                    "error",
                    "investigator_role_mismatch",
                    f"{filename} does not identify "
                    "Dr. Ananya Sharma as Principal Investigator.",
                    [filename],
                )

        if "rahul verma" in name:
            if "co-investigator" not in role:
                add_issue(
                    issues,
                    "error",
                    "investigator_role_mismatch",
                    f"{filename} does not identify "
                    "Dr. Rahul Verma as Co-Investigator.",
                    [filename],
                )

    return issues


def validate_collaborator_documents(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Check that every named investigator has a corresponding
    investigator document in the packet.
    """

    issues: List[Dict[str, Any]] = []

    # Names for which an investigator CV/biosketch exists.
    documented_people = set()

    for document in extracted_documents:
        if document["document_type"] != "investigator_cv":
            continue

        name = normalize_person_name(
            document["facts"].get("name", "")
        )

        if name:
            documented_people.add(name)

    # Names mentioned by the grant documents.
    named_people = set()

    for document in extracted_documents:
        facts = document["facts"]

        for field in (
            "principal_investigator",
            "co_investigator",
        ):
            name = normalize_person_name(
                facts.get(field, "")
            )

            if name:
                named_people.add(name)

    # Every named investigator must have a corresponding
    # investigator document.
    for person in sorted(named_people):
        if person not in documented_people:
            add_issue(
                issues,
                "error",
                "missing_collaborator_document",
                f"No investigator document found for {person}.",
                [],
            )

    return issues


def validate_documents(
    extracted_documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Run all cross-document validation checks."""

    issues: List[Dict[str, Any]] = []

    # 1. Project identity consistency
    issues.extend(
        validate_project_identity(
            extracted_documents
        )
    )

    # 2. Investigator identity consistency
    issues.extend(
        validate_investigators(
            extracted_documents
        )
    )

    # 3. Required fields
    issues.extend(
        validate_required_fields(
            extracted_documents
        )
    )

    # 4. Investigator role consistency
    issues.extend(
        validate_investigator_roles(
            extracted_documents
        )
    )

    # 5. Every named investigator must have
    #    a corresponding investigator document.
    issues.extend(
        validate_collaborator_documents(
            extracted_documents
        )
    )

    errors = [
        issue
        for issue in issues
        if issue["severity"] == "error"
    ]

    warnings = [
        issue
        for issue in issues
        if issue["severity"] == "warning"
    ]

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "issues": issues,
        "issue_count": len(issues),
    }