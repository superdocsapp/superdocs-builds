from pathlib import Path
from typing import Any, Dict, List

from app.assemble import build_grant_package
from app.biosketch import convert_investigator_to_biosketch
from app.classify import classify_document
from app.extract import (
    extract_budget_justification,
    extract_data_management_plan,
    extract_facilities_statement,
    extract_investigator_cv,
    extract_research_narrative,
)
from app.ingest import ingest_directory
from app.output import save_grant_package
from app.validate import validate_documents


def extract_facts(
    document_type: str,
    content: str,
) -> Dict[str, Any]:
    """Run the appropriate extractor for a document type."""

    extractors = {
        "research_narrative": extract_research_narrative,
        "data_management_plan": extract_data_management_plan,
        "investigator_cv": extract_investigator_cv,
        "facilities_statement": extract_facilities_statement,
        "budget_justification": extract_budget_justification,
    }

    extractor = extractors.get(document_type)

    if extractor is None:
        return {}

    return extractor(content)


def build_extracted_documents(
    grant_directory: str | Path,
) -> List[Dict[str, Any]]:
    """Ingest, classify, and extract all supported grant documents."""

    documents = ingest_directory(grant_directory)

    extracted_documents = []

    for document in documents:
        document_type = classify_document(
            document["filename"],
            document["content"],
        )

        facts = extract_facts(
            document_type,
            document["content"],
        )

        extracted_documents.append(
            {
                "filename": document["filename"],
                "path": document["path"],
                "extension": document["extension"],
                "document_type": document_type,
                "characters": document["characters"],
                "facts": facts,
            }
        )

    return extracted_documents


def build_biosketches(
    extracted_documents: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Convert every investigator CV into a funder-style biosketch.

    The original extracted CV facts remain untouched. Each biosketch
    carries an explicit content-preservation result.
    """

    biosketches = []

    for document in extracted_documents:
        if document["document_type"] != "investigator_cv":
            continue

        facts = document.get("facts", {})

        biosketch = convert_investigator_to_biosketch(
            facts
        )

        biosketches.append(
            {
                "source_document": document["filename"],
                "investigator": biosketch["name"],
                "format": biosketch["format"],
                "rendered_text": biosketch["rendered_text"],
                "content_preservation": biosketch[
                    "content_preservation"
                ],
            }
        )

    return biosketches


def run_validation(
    grant_directory: str | Path,
) -> Dict[str, Any]:
    """Build the structured grant corpus and validate it."""

    extracted_documents = build_extracted_documents(
        grant_directory
    )

    validation = validate_documents(
        extracted_documents
    )

    return {
        "documents": extracted_documents,
        "validation": validation,
    }


def run_grant_assembly(
    grant_directory: str | Path,
    output_path: str | Path = "output/grant_package.json",
) -> Dict[str, Any]:
    """Run extraction, biosketch conversion, validation, assembly, and persistence."""

    extracted_documents = build_extracted_documents(
        grant_directory
    )

    biosketches = build_biosketches(
        extracted_documents
    )

    validation = validate_documents(
        extracted_documents
    )

    grant_package = build_grant_package(
        extracted_documents
    )

    # Keep generated biosketches alongside the assembled grant package.
    grant_package["biosketches"] = biosketches

    saved_path = save_grant_package(
        grant_package,
        output_path,
    )

    return {
        "documents": extracted_documents,
        "biosketches": biosketches,
        "validation": validation,
        "grant_package": grant_package,
        "output_path": str(saved_path),
    }