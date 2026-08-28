"""Classify document node for the Understand stage.

Classifies an ingested document by type using a pluggable classifier service.
Stores the classification label, confidence, and per-label scores in state.

If all scores are at or below 0.6, the document is labelled "unclassified"
and routed to the approval queue for human review.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Protocol

from src.pipeline.state import PipelineState

NODE_NAME = "classify_document"

# Supported MIME types for document ingestion
SUPPORTED_MIME_TYPES: set[str] = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

# --- Types ---

DocumentType = Literal[
    "loan_agreement",
    "modification_agreement",
    "repayment_statement",
    "unclassified",
]


@dataclass
class ClassificationResult:
    """Result of document classification."""

    label: DocumentType
    confidence: float  # 0.0–1.0
    scores: dict[str, float]  # per-label scores


class DocumentClassifierService(Protocol):
    """Protocol for the classification backend (LLM or ML model)."""

    async def classify(self, text: str) -> ClassificationResult: ...


# --- Node Implementation ---


async def classify_document(
    state: PipelineState,
    *,
    classifier: Optional[DocumentClassifierService] = None,
) -> PipelineState:
    """Classify the document by type and store result in state.

    Node contract:
        Input keys: extracted_text
        Output keys: classification_label, classification_confidence,
                     classification_scores, current_node, node_status,
                     error_type, error_detail, completed_nodes

    Terminal states:
        - completed: classification successful (including "unclassified" label)
        - error/transient: classifier is None or raises a transient error

    If max confidence <= 0.6, sets label to 'unclassified' and the downstream
    routing function (route_to_queue) handles escalation to the approval queue.

    Args:
        state: The current pipeline state.
        classifier: Optional classifier service (dependency injection).

    Returns:
        Updated PipelineState with classification results or error information.
    """
    # Validate MIME type before proceeding
    mime_type = state.get("mime_type")  # type: ignore[call-overload]
    if mime_type is not None and mime_type not in SUPPORTED_MIME_TYPES:
        return _permanent_error_state(
            state,
            error_detail=f"UNSUPPORTED_FORMAT: MIME type '{mime_type}' is not supported. "
            f"Supported types: PDF, DOCX, plain text.",
        )

    # No classifier provided — configuration error, treat as transient
    if classifier is None:
        return _transient_error_state(
            state,
            error_detail="No classifier service provided (configuration error)",
        )

    extracted_text = state.get("extracted_text")  # type: ignore[call-overload]

    # If there's no text to classify, return a permanent error (parse failure)
    if extracted_text is None or len(extracted_text) == 0:
        return _permanent_error_state(
            state,
            error_detail="PARSE_FAILURE: No extracted text available for classification. "
            "The document could not be parsed or contains no extractable text.",
        )

    try:
        result = await classifier.classify(extracted_text)
    except Exception as exc:
        # Any exception from the classifier is treated as a transient error
        return _transient_error_state(
            state,
            error_detail=f"Classifier service error: {exc}",
        )

    # Check if all scores are at or below 0.6 threshold
    max_score = max(result.scores.values()) if result.scores else 0.0
    if max_score <= 0.6:
        # Label as unclassified — routing logic handles escalation
        completed_nodes = list(state.get("completed_nodes", []))  # type: ignore[call-overload]
        completed_nodes.append(NODE_NAME)
        return PipelineState(
            **{
                **state,
                "classification_label": "unclassified",
                "classification_confidence": result.confidence,
                "classification_scores": result.scores,
                "current_node": NODE_NAME,
                "node_status": "completed",
                "error_type": None,
                "error_detail": None,
                "completed_nodes": completed_nodes,
            }
        )

    # Normal classification — use the result label and confidence
    completed_nodes = list(state.get("completed_nodes", []))  # type: ignore[call-overload]
    completed_nodes.append(NODE_NAME)
    return PipelineState(
        **{
            **state,
            "classification_label": result.label,
            "classification_confidence": result.confidence,
            "classification_scores": result.scores,
            "current_node": NODE_NAME,
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "completed_nodes": completed_nodes,
        }
    )


def _transient_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a transient error state for classify_document."""
    return PipelineState(
        **{
            **state,
            "current_node": NODE_NAME,
            "node_status": "error",
            "error_type": "transient",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),  # type: ignore[call-overload]
        }
    )


def _permanent_error_state(
    state: PipelineState, *, error_detail: str
) -> PipelineState:
    """Return a permanent error state for classify_document."""
    return PipelineState(
        **{
            **state,
            "current_node": NODE_NAME,
            "node_status": "error",
            "error_type": "permanent",
            "error_detail": error_detail,
            "completed_nodes": list(state.get("completed_nodes", [])),  # type: ignore[call-overload]
        }
    )
