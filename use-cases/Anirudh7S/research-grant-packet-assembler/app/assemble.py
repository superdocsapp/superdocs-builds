from typing import Any, Dict, List


def find_document(
    documents: List[Dict[str, Any]],
    document_type: str,
) -> Dict[str, Any]:
    """Find the first document matching a document type."""

    for document in documents:
        if document["document_type"] == document_type:
            return document

    return {}


def build_grant_package(
    extracted_documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble extracted grant facts into one structured package."""

    research = find_document(
        extracted_documents,
        "research_narrative",
    )

    data_management = find_document(
        extracted_documents,
        "data_management_plan",
    )

    facilities = find_document(
        extracted_documents,
        "facilities_statement",
    )

    budget = find_document(
        extracted_documents,
        "budget_justification",
    )

    investigator_documents = [
        document
        for document in extracted_documents
        if document["document_type"] == "investigator_cv"
    ]

    research_facts = research.get("facts", {})
    dmp_facts = data_management.get("facts", {})
    facilities_facts = facilities.get("facts", {})
    budget_facts = budget.get("facts", {})

    investigators = []

    for document in investigator_documents:
        facts = document.get("facts", {})

        investigators.append(
            {
                "filename": document["filename"],
                "name": facts.get("name", ""),
                "current_position": facts.get(
                    "current_position",
                    "",
                ),
                "education": facts.get(
                    "education",
                    [],
                ),
                "research_interests": facts.get(
                    "research_interests",
                    [],
                ),
                "professional_experience": facts.get(
                    "professional_experience",
                    [],
                ),
                "selected_publications": facts.get(
                    "selected_publications",
                    [],
                ),
                "awards": facts.get(
                    "awards",
                    [],
                ),
                "current_grant_role": facts.get(
                    "current_grant_role",
                    "",
                ),
            }
        )

    grant_package = {
        "project": {
            "title": research_facts.get(
                "project_title",
                "",
            ),
            "principal_investigator": research_facts.get(
                "principal_investigator",
                "",
            ),
            "co_investigator": research_facts.get(
                "co_investigator",
                "",
            ),
        },

        "research_narrative": {
            "project_summary": research_facts.get(
                "project_summary",
                "",
            ),
            "specific_aims": research_facts.get(
                "specific_aims",
                [],
            ),
            "research_approach": research_facts.get(
                "research_approach",
                "",
            ),
            "expected_outcomes": research_facts.get(
                "expected_outcomes",
                "",
            ),
            "significance": research_facts.get(
                "significance",
                "",
            ),
        },

        "data_management_plan": {
            "project": dmp_facts.get(
                "project",
                "",
            ),
            "principal_investigator": dmp_facts.get(
                "principal_investigator",
                "",
            ),
            "co_investigator": dmp_facts.get(
                "co_investigator",
                "",
            ),
            "data_types": dmp_facts.get(
                "data_types",
                "",
            ),
            "data_collection": dmp_facts.get(
                "data_collection",
                "",
            ),
            "data_storage": dmp_facts.get(
                "data_storage",
                "",
            ),
            "data_security": dmp_facts.get(
                "data_security",
                "",
            ),
            "data_quality": dmp_facts.get(
                "data_quality",
                "",
            ),
            "data_sharing": dmp_facts.get(
                "data_sharing",
                "",
            ),
            "data_retention": dmp_facts.get(
                "data_retention",
                "",
            ),
        },

        "investigators": investigators,

        "facilities_statement": {
            "project": facilities_facts.get(
                "project",
                "",
            ),
            "facilities_and_sites": facilities_facts.get(
                "facilities_and_sites",
                "",
            ),
            "space_and_screening": facilities_facts.get(
                "space_and_screening",
                "",
            ),
            "data_systems": facilities_facts.get(
                "data_systems",
                "",
            ),
            "institutional_support": facilities_facts.get(
                "institutional_support",
                "",
            ),
            "investigator_responsibilities": facilities_facts.get(
                "investigator_responsibilities",
                "",
            ),
        },

        "budget_justification": {
            "personnel": budget_facts.get(
                "personnel",
                "",
            ),
            "principal_investigator": budget_facts.get(
                "principal_investigator",
                "",
            ),
            "co_investigator": budget_facts.get(
                "co_investigator",
                "",
            ),
            "participant_and_site_activities": budget_facts.get(
                "participant_and_site_activities",
                "",
            ),
            "data_management": budget_facts.get(
                "data_management",
                "",
            ),
            "dissemination": budget_facts.get(
                "dissemination",
                "",
            ),
        },

        "source_documents": [
            {
                "filename": document["filename"],
                "document_type": document["document_type"],
            }
            for document in extracted_documents
        ],
    }

    return grant_package