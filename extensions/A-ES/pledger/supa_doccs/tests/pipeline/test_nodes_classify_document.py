"""Unit tests for the classify_document node."""

import pytest

from src.pipeline.nodes.classify_document import (
    ClassificationResult,
    DocumentClassifierService,
    SUPPORTED_MIME_TYPES,
    classify_document,
)
from src.pipeline.state import (
    PipelineConfig,
    PipelineState,
    create_initial_state,
)


def _make_config() -> PipelineConfig:
    """Create a default PipelineConfig for tests."""
    return PipelineConfig(
        max_retries=3,
        chunk_max_size=1000,
        chunk_overlap=200,
        confidence_threshold=0.7,
        review_timeout_hours=72,
        reminder_interval_hours=24,
        poll_interval_seconds=30,
        extract_text_timeout_seconds=60,
        min_chunk_threshold=200,
    )


def _make_state(
    extracted_text: str | None = "Sample document text.",
    mime_type: str | None = "application/pdf",
) -> PipelineState:
    """Create an initial pipeline state with given extracted_text and mime_type."""
    state = create_initial_state(
        run_id="run-001",
        document_id="doc-001",
        document_version_id="ver-001",
        config=_make_config(),
    )
    state["extracted_text"] = extracted_text  # type: ignore[typeddict-item]
    state["mime_type"] = mime_type  # type: ignore[typeddict-item]
    return state


class FakeClassifier:
    """A fake classifier that returns a pre-configured result."""

    def __init__(self, result: ClassificationResult) -> None:
        self._result = result

    async def classify(self, text: str) -> ClassificationResult:
        return self._result


class ErrorClassifier:
    """A fake classifier that raises an exception."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def classify(self, text: str) -> ClassificationResult:
        raise self._error


@pytest.mark.anyio
async def test_successful_classification_loan_agreement():
    """Successful classification stores label, confidence, and scores in state."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.92,
        scores={
            "loan_agreement": 0.92,
            "modification_agreement": 0.05,
            "repayment_statement": 0.03,
        },
    )
    classifier = FakeClassifier(result)
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["current_node"] == "classify_document"
    assert output["classification_label"] == "loan_agreement"
    assert output["classification_confidence"] == 0.92
    assert output["classification_scores"] == {
        "loan_agreement": 0.92,
        "modification_agreement": 0.05,
        "repayment_statement": 0.03,
    }
    assert output["error_type"] is None
    assert output["error_detail"] is None
    assert "classify_document" in output["completed_nodes"]


@pytest.mark.anyio
async def test_successful_classification_modification_agreement():
    """Classification correctly assigns modification_agreement label."""
    result = ClassificationResult(
        label="modification_agreement",
        confidence=0.85,
        scores={
            "loan_agreement": 0.10,
            "modification_agreement": 0.85,
            "repayment_statement": 0.05,
        },
    )
    classifier = FakeClassifier(result)
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "modification_agreement"
    assert output["classification_confidence"] == 0.85


@pytest.mark.anyio
async def test_unclassified_when_all_scores_at_or_below_threshold():
    """When all scores <= 0.6, label is set to 'unclassified'."""
    result = ClassificationResult(
        label="loan_agreement",  # original label from classifier
        confidence=0.55,
        scores={
            "loan_agreement": 0.55,
            "modification_agreement": 0.30,
            "repayment_statement": 0.15,
        },
    )
    classifier = FakeClassifier(result)
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "unclassified"
    assert output["classification_confidence"] == 0.55
    assert output["classification_scores"] == {
        "loan_agreement": 0.55,
        "modification_agreement": 0.30,
        "repayment_statement": 0.15,
    }
    assert output["error_type"] is None
    assert "classify_document" in output["completed_nodes"]


@pytest.mark.anyio
async def test_unclassified_when_max_score_exactly_0_6():
    """Boundary: max score == 0.6 results in 'unclassified'."""
    result = ClassificationResult(
        label="repayment_statement",
        confidence=0.6,
        scores={
            "loan_agreement": 0.2,
            "modification_agreement": 0.2,
            "repayment_statement": 0.6,
        },
    )
    classifier = FakeClassifier(result)
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["classification_label"] == "unclassified"
    assert output["node_status"] == "completed"


@pytest.mark.anyio
async def test_classified_when_max_score_above_0_6():
    """When max score > 0.6, the classifier's label is used."""
    result = ClassificationResult(
        label="repayment_statement",
        confidence=0.61,
        scores={
            "loan_agreement": 0.2,
            "modification_agreement": 0.19,
            "repayment_statement": 0.61,
        },
    )
    classifier = FakeClassifier(result)
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["classification_label"] == "repayment_statement"
    assert output["node_status"] == "completed"


@pytest.mark.anyio
async def test_transient_error_when_classifier_is_none():
    """When no classifier is provided, returns transient error."""
    state = _make_state()

    output = await classify_document(state, classifier=None)

    assert output["node_status"] == "error"
    assert output["current_node"] == "classify_document"
    assert output["error_type"] == "transient"
    assert "No classifier service provided" in output["error_detail"]
    assert "classify_document" not in output["completed_nodes"]


@pytest.mark.anyio
async def test_transient_error_when_classifier_raises():
    """When classifier raises an exception, returns transient error."""
    classifier = ErrorClassifier(RuntimeError("Connection timeout"))
    state = _make_state()

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["current_node"] == "classify_document"
    assert output["error_type"] == "transient"
    assert "Classifier service error" in output["error_detail"]
    assert "Connection timeout" in output["error_detail"]
    assert "classify_document" not in output["completed_nodes"]


@pytest.mark.anyio
async def test_permanent_error_when_extracted_text_is_none():
    """When extracted_text is None, returns permanent error with PARSE_FAILURE."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.9,
        scores={"loan_agreement": 0.9},
    )
    classifier = FakeClassifier(result)
    state = _make_state(extracted_text=None)

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["error_type"] == "permanent"
    assert "PARSE_FAILURE" in output["error_detail"]


@pytest.mark.anyio
async def test_permanent_error_when_extracted_text_is_empty():
    """When extracted_text is empty string, returns permanent error with PARSE_FAILURE."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.9,
        scores={"loan_agreement": 0.9},
    )
    classifier = FakeClassifier(result)
    state = _make_state(extracted_text="")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["error_type"] == "permanent"
    assert "PARSE_FAILURE" in output["error_detail"]


@pytest.mark.anyio
async def test_state_immutability():
    """The original state should not be mutated by classify_document."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.92,
        scores={"loan_agreement": 0.92},
    )
    classifier = FakeClassifier(result)
    state = _make_state()
    original_completed = list(state["completed_nodes"])

    output = await classify_document(state, classifier=classifier)

    # Original state's completed_nodes should be unchanged
    assert state["completed_nodes"] == original_completed
    # Output should have classify_document appended
    assert "classify_document" in output["completed_nodes"]


# --- MIME Type Validation Tests ---


@pytest.mark.anyio
async def test_unsupported_mime_type_returns_permanent_error():
    """Unsupported MIME type returns permanent error with UNSUPPORTED_FORMAT."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.9,
        scores={"loan_agreement": 0.9},
    )
    classifier = FakeClassifier(result)
    state = _make_state(mime_type="image/png")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["current_node"] == "classify_document"
    assert output["error_type"] == "permanent"
    assert "UNSUPPORTED_FORMAT" in output["error_detail"]
    assert "image/png" in output["error_detail"]
    assert "classify_document" not in output["completed_nodes"]


@pytest.mark.anyio
async def test_unsupported_mime_type_application_xml():
    """application/xml is not supported and returns UNSUPPORTED_FORMAT."""
    classifier = FakeClassifier(
        ClassificationResult(label="loan_agreement", confidence=0.9, scores={"loan_agreement": 0.9})
    )
    state = _make_state(mime_type="application/xml")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["error_type"] == "permanent"
    assert "UNSUPPORTED_FORMAT" in output["error_detail"]


@pytest.mark.anyio
async def test_supported_mime_type_pdf_passes_through():
    """application/pdf is supported and classification proceeds normally."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.92,
        scores={"loan_agreement": 0.92, "modification_agreement": 0.05, "repayment_statement": 0.03},
    )
    classifier = FakeClassifier(result)
    state = _make_state(mime_type="application/pdf")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "loan_agreement"


@pytest.mark.anyio
async def test_supported_mime_type_docx_passes_through():
    """DOCX MIME type is supported and classification proceeds normally."""
    result = ClassificationResult(
        label="modification_agreement",
        confidence=0.85,
        scores={"loan_agreement": 0.1, "modification_agreement": 0.85, "repayment_statement": 0.05},
    )
    classifier = FakeClassifier(result)
    state = _make_state(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "modification_agreement"


@pytest.mark.anyio
async def test_supported_mime_type_text_plain_passes_through():
    """text/plain is supported and classification proceeds normally."""
    result = ClassificationResult(
        label="repayment_statement",
        confidence=0.78,
        scores={"loan_agreement": 0.1, "modification_agreement": 0.12, "repayment_statement": 0.78},
    )
    classifier = FakeClassifier(result)
    state = _make_state(mime_type="text/plain")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "repayment_statement"


@pytest.mark.anyio
async def test_none_mime_type_does_not_reject():
    """When mime_type is None (not yet set), MIME validation is skipped."""
    result = ClassificationResult(
        label="loan_agreement",
        confidence=0.92,
        scores={"loan_agreement": 0.92, "modification_agreement": 0.05, "repayment_statement": 0.03},
    )
    classifier = FakeClassifier(result)
    state = _make_state(mime_type=None)

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "completed"
    assert output["classification_label"] == "loan_agreement"


@pytest.mark.anyio
async def test_parse_failure_with_supported_mime_and_none_text():
    """Supported MIME type but None extracted_text returns PARSE_FAILURE."""
    classifier = FakeClassifier(
        ClassificationResult(label="loan_agreement", confidence=0.9, scores={"loan_agreement": 0.9})
    )
    state = _make_state(mime_type="application/pdf", extracted_text=None)

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["error_type"] == "permanent"
    assert "PARSE_FAILURE" in output["error_detail"]


@pytest.mark.anyio
async def test_parse_failure_with_supported_mime_and_empty_text():
    """Supported MIME type but empty extracted_text returns PARSE_FAILURE."""
    classifier = FakeClassifier(
        ClassificationResult(label="loan_agreement", confidence=0.9, scores={"loan_agreement": 0.9})
    )
    state = _make_state(mime_type="text/plain", extracted_text="")

    output = await classify_document(state, classifier=classifier)

    assert output["node_status"] == "error"
    assert output["error_type"] == "permanent"
    assert "PARSE_FAILURE" in output["error_detail"]
