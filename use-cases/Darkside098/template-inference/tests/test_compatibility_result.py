"""Tests for compatibility result models."""

import json
from dataclasses import asdict

from superdocs_template_inference.compatibility import CompatibilityEvidence, CompatibilityResult


def test_compatibility_evidence_model():
    """CompatibilityEvidence stores observable evidence fields."""
    evidence = CompatibilityEvidence(
        type="structural",
        signal_name="block_structure_similarity",
        value=0.88,
        description="Block counts are close.",
        details={"a_total_blocks": 12, "b_total_blocks": 10},
    )

    assert evidence.type == "structural"
    assert evidence.signal_name == "block_structure_similarity"
    assert 0.0 <= evidence.value <= 1.0
    assert evidence.details["a_total_blocks"] == 12


def test_compatibility_result_model_has_required_fields():
    """CompatibilityResult exposes the required deterministic fields."""
    result = CompatibilityResult(
        profile_a_id="a-1",
        profile_b_id="b-2",
        profile_a_filename="a.docx",
        profile_b_filename="b.docx",
        score=0.82,
        confidence=0.75,
        compatible=True,
        threshold=0.65,
        evidence=[
            CompatibilityEvidence(
                type="structural",
                signal_name="block_structure_similarity",
                value=0.82,
                description="Close structure",
                details={},
            )
        ],
        signal_scores={"block_structure_similarity": 0.82},
    )

    assert result.profile_a_id == "a-1"
    assert result.profile_b_id == "b-2"
    assert result.profile_a_filename == "a.docx"
    assert result.profile_b_filename == "b.docx"
    assert result.score == 0.82
    assert result.confidence == 0.75
    assert result.compatible is True
    assert result.threshold == 0.65
    assert len(result.evidence) == 1
    assert result.comparison_version == "1.0"


def test_compatibility_result_serializes_to_json():
    """CompatibilityResult serializes with standard library dataclass/json support."""
    result = CompatibilityResult(
        profile_a_id="a-1",
        profile_b_id="b-2",
        profile_a_filename="a.docx",
        profile_b_filename="b.docx",
        score=0.74,
        confidence=0.7,
        compatible=True,
        threshold=0.65,
        evidence=[],
        signal_scores={},
    )

    payload = json.dumps(asdict(result))
    assert "profile_a_id" in payload
    assert "comparison_version" in payload
    assert "score" in payload
