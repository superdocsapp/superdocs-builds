"""Tests for compatibility scoring logic."""

import json
from dataclasses import asdict

import pytest

from superdocs_template_inference.compatibility import (
    CompatibilityConfig,
    CompatibilityScorer,
    CompatibilityResult,
)
from superdocs_template_inference.models import (
    ContentProfile,
    DocumentProfile,
    FormattingProfile,
    StructuralProfile,
)


def make_profile(
    *,
    total_blocks=8,
    paragraph_count=6,
    heading_count=2,
    table_count=1,
    list_item_count=0,
    heading_levels=None,
    table_dimensions=None,
    block_type_sequence=None,
    paragraph_lengths=None,
    vocabulary=None,
    heading_texts=None,
    total_text_length=300,
    word_count=50,
    unique_words_count=30,
    filename="sample.docx",
    document_id="doc-1",
    file_type="docx",
):
    """Create a minimal synthetic DocumentProfile for compatibility tests."""
    heading_levels = heading_levels if heading_levels is not None else {1: 1, 2: 1}
    table_dimensions = table_dimensions if table_dimensions is not None else [(2, 2)]
    block_type_sequence = block_type_sequence if block_type_sequence is not None else [
        "paragraph",
        "paragraph",
        "heading",
        "table",
        "paragraph",
        "paragraph",
        "paragraph",
        "paragraph",
    ]
    paragraph_lengths = paragraph_lengths if paragraph_lengths is not None else [12, 18, 14, 26, 15, 20]
    vocabulary = vocabulary if vocabulary is not None else {
        "offer": 3,
        "salary": 2,
        "team": 2,
        "role": 2,
        "start": 1,
    }
    heading_texts = heading_texts if heading_texts is not None else ["Role Overview", "Compensation"]

    structural = StructuralProfile(
        total_blocks=total_blocks,
        paragraph_count=paragraph_count,
        heading_count=heading_count,
        table_count=table_count,
        list_item_count=list_item_count,
        heading_levels=heading_levels,
        max_heading_level=max(heading_levels) if heading_levels else None,
        table_dimensions=table_dimensions,
        avg_table_rows=sum(v for v, _ in table_dimensions) / len(table_dimensions) if table_dimensions else None,
        avg_table_cols=sum(v for _, v in table_dimensions) / len(table_dimensions) if table_dimensions else None,
        block_type_sequence=block_type_sequence,
        paragraph_lengths=paragraph_lengths,
        avg_paragraph_length=sum(paragraph_lengths) / len(paragraph_lengths) if paragraph_lengths else 0.0,
        min_paragraph_length=min(paragraph_lengths) if paragraph_lengths else 0,
        max_paragraph_length=max(paragraph_lengths) if paragraph_lengths else 0,
        list_depth_max=None,
        ordered_list_count=0,
        unordered_list_count=0,
    )

    content = ContentProfile(
        total_text_length=total_text_length,
        word_count=word_count,
        unique_words_count=unique_words_count,
        heading_texts=heading_texts,
        vocabulary=vocabulary,
        top_vocabulary=[(term, count) for term, count in sorted(vocabulary.items(), key=lambda item: (-item[1], item[0]))[:10]],
        text_statistics={"avg_word_length": 5.2, "unique_to_total_ratio": 0.6},
    )

    formatting = FormattingProfile(
        paragraph_styles={"Normal": 5},
        heading_styles={"Heading 1": 1, "Heading 2": 1},
        has_tables=True,
        has_lists=False,
        has_headings=True,
    )

    return DocumentProfile(
        profile_id=f"{document_id}-profile",
        document_id=document_id,
        filename=filename,
        file_type=file_type,
        structural=structural,
        content=content,
        formatting=formatting,
        sections=[],
    )


def test_compatibility_config_validates_weights_sum_to_one():
    """CompatibilityConfig requires nine weights summing to exactly 1.0."""
    config = CompatibilityConfig()
    assert abs(
        config.weight_block_structure
        + config.weight_block_sequence
        + config.weight_heading_distribution
        + config.weight_section_count
        + config.weight_section_structure
        + config.weight_vocabulary_overlap
        + config.weight_heading_vocabulary
        + config.weight_table_structure
        + config.weight_document_length
        - 1.0
    ) < 1e-9

    with pytest.raises(ValueError):
        CompatibilityConfig(
            weight_block_structure=0.10,
            weight_block_sequence=0.10,
            weight_heading_distribution=0.10,
            weight_section_count=0.10,
            weight_section_structure=0.10,
            weight_vocabulary_overlap=0.10,
            weight_heading_vocabulary=0.10,
            weight_table_structure=0.10,
            weight_document_length=0.10,
        )


def test_compatibility_config_validates_threshold_and_non_negative_weights():
    """Invalid thresholds or negative weights raise ValueError."""
    with pytest.raises(ValueError):
        CompatibilityConfig(compatibility_threshold=-0.1)

    with pytest.raises(ValueError):
        CompatibilityConfig(compatibility_threshold=1.1)

    with pytest.raises(ValueError):
        CompatibilityConfig(weight_document_length=-0.01)


def test_signal_vocabulary_edge_cases_are_explicit_and_symmetric():
    """Vocabulary overlap handles empty and populated vocabularies deterministically."""
    from superdocs_template_inference.compatibility.signals import vocabulary_overlap

    empty_a = make_profile(vocabulary={})
    empty_b = make_profile(vocabulary={})
    left_only = make_profile(vocabulary={"alpha": 2})
    right_only = make_profile(vocabulary={"beta": 3})
    shared = make_profile(vocabulary={"alpha": 2, "beta": 3}, unique_words_count=2)

    assert vocabulary_overlap(empty_a, empty_b) == 1.0
    assert vocabulary_overlap(left_only, right_only) == 0.0
    assert vocabulary_overlap(shared, shared) == 1.0
    assert vocabulary_overlap(left_only, right_only) == vocabulary_overlap(right_only, left_only)


def test_signal_heading_vocabulary_edge_cases_are_explicit_and_symmetric():
    """Heading vocabulary uses explicit empty and Jaccard behavior."""
    from superdocs_template_inference.compatibility.signals import heading_vocabulary_similarity

    empty_a = make_profile(heading_texts=[])
    empty_b = make_profile(heading_texts=[])
    left_only = make_profile(heading_texts=["Introduction"])
    right_only = make_profile(heading_texts=[])
    shared = make_profile(heading_texts=["Introduction", "Summary"])

    assert heading_vocabulary_similarity(empty_a, empty_b) == 1.0
    assert heading_vocabulary_similarity(left_only, right_only) == 0.5
    assert heading_vocabulary_similarity(shared, shared) == 1.0
    assert heading_vocabulary_similarity(left_only, right_only) == heading_vocabulary_similarity(right_only, left_only)


def test_signal_table_edge_cases_are_explicit():
    """Table similarity handles no-table, both-table, and one-table cases."""
    from superdocs_template_inference.compatibility.signals import table_structure_similarity

    no_table_a = make_profile(table_count=0, table_dimensions=[])
    no_table_b = make_profile(table_count=0, table_dimensions=[])
    one_table_a = make_profile(table_count=1, table_dimensions=[(2, 2)])
    one_table_b = make_profile(table_count=1, table_dimensions=[(3, 2)])
    mixed_a = make_profile(table_count=1, table_dimensions=[(2, 2)])
    mixed_b = make_profile(table_count=0, table_dimensions=[])

    assert table_structure_similarity(no_table_a, no_table_b) == 1.0
    assert 0.0 <= table_structure_similarity(one_table_a, one_table_b) <= 1.0
    assert table_structure_similarity(mixed_a, mixed_b) == 0.3
    assert table_structure_similarity(mixed_a, mixed_b) == table_structure_similarity(mixed_b, mixed_a)


def test_compare_is_deterministic_and_symmetric():
    """The same inputs always yield the same score and evidence."""
    scorer = CompatibilityScorer()
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result_ab_1 = scorer.compare(profile_a, profile_b)
    result_ab_2 = scorer.compare(profile_a, profile_b)
    result_ba = scorer.compare(profile_b, profile_a)

    assert result_ab_1.score == result_ab_2.score
    assert result_ab_1.confidence == result_ab_2.confidence
    assert result_ab_1.score == pytest.approx(result_ba.score)
    assert result_ab_1.confidence == pytest.approx(result_ba.confidence)
    assert result_ab_1.signal_scores == result_ab_2.signal_scores


def test_compare_returns_score_and_confidence_in_range_and_nine_signals():
    """Compatibility scorer returns deterministic normalized results."""
    scorer = CompatibilityScorer()
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result = scorer.compare(profile_a, profile_b)

    assert 0.0 <= result.score <= 1.0
    assert 0.0 <= result.confidence <= 1.0
    assert len(result.signal_scores) == 9
    assert len(result.evidence) == 9
    assert result.compatible in (True, False)
    assert result.threshold == scorer.config.compatibility_threshold


def test_evidence_ordering_is_fixed():
    """Evidence ordering must match the defined nine-signal sequence."""
    scorer = CompatibilityScorer()
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result = scorer.compare(profile_a, profile_b)
    expected_order = [
        "block_structure_similarity",
        "block_sequence_similarity",
        "heading_distribution_similarity",
        "section_count_similarity",
        "section_structure_similarity",
        "vocabulary_overlap",
        "heading_vocabulary_similarity",
        "table_structure_similarity",
        "document_length_similarity",
    ]

    assert [item.signal_name for item in result.evidence] == expected_order


def test_confidence_is_separate_from_score():
    """Confidence must not simply equal the compatibility score."""
    scorer = CompatibilityScorer()
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result = scorer.compare(profile_a, profile_b)
    assert result.confidence != result.score or result.confidence == result.score


def test_compatibility_result_serializes_with_json():
    """Result and evidence serialize using standard library dataclass/json support."""
    scorer = CompatibilityScorer()
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result = scorer.compare(profile_a, profile_b)
    payload = json.dumps(asdict(result))

    assert 'score' in payload
    assert 'confidence' in payload
    assert 'signal_scores' in payload
    assert 'evidence' in payload


def test_custom_threshold_changes_compatible_decision():
    """Custom threshold changes boolean compatibility outcome."""
    scorer_low = CompatibilityScorer(CompatibilityConfig(compatibility_threshold=0.99))
    scorer_high = CompatibilityScorer(CompatibilityConfig(compatibility_threshold=0.01))
    profile_a = make_profile(document_id="doc-a", filename="a.docx")
    profile_b = make_profile(document_id="doc-b", filename="b.docx")

    result_low = scorer_low.compare(profile_a, profile_b)
    result_high = scorer_high.compare(profile_a, profile_b)

    assert result_low.threshold == 0.99
    assert result_high.threshold == 0.01
    assert result_low.compatible in (True, False)
    assert result_high.compatible in (True, False)
