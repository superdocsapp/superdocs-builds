from pathlib import Path

import pytest

from edit_precision_evaluator.corpus import load_corpus, validate_corpus
from edit_precision_evaluator.html_units import extract_units
from edit_precision_evaluator.models import CorpusCase
from edit_precision_evaluator.scorer import score_edit


def make_case(scopes: list[dict]) -> CorpusCase:
    return CorpusCase.model_validate(
        {
            "case_id": "test-case",
            "document": "test.html",
            "instruction": "Change the target.",
            "instruction_type": "single_sentence",
            "label_rationale": "Test fixture.",
            "labeler": "test",
            "acceptable_scopes": scopes,
        }
    )


def test_perfect_targeted_edit_has_full_coverage_and_no_collateral() -> None:
    before = '<p data-chunk-id="target">Old value</p><p data-chunk-id="safe">Keep me</p>'
    after = '<p data-chunk-id="target">New value</p><p data-chunk-id="safe">Keep me</p>'
    case = make_case(
        [
            {
                "scope_id": "only-target",
                "expected_change_ids": ["target"],
                "protected_ids": ["safe"],
                "required_after_fragments": {"target": ["New value"]},
                "explanation": "Only target changes.",
            }
        ]
    )

    score = score_edit(case, before, after)

    assert score.intended_change_coverage == 1
    assert score.collateral_damage_rate == 0
    assert score.precision_loss == 0


def test_missed_target_is_reported() -> None:
    html = '<p data-chunk-id="target">Old value</p><p data-chunk-id="safe">Keep me</p>'
    case = make_case(
        [
            {
                "scope_id": "only-target",
                "expected_change_ids": ["target"],
                "protected_ids": ["safe"],
                "explanation": "Only target changes.",
            }
        ]
    )

    score = score_edit(case, html, html)

    assert score.intended_change_coverage == 0
    assert score.missing_expected_ids == ["target"]
    assert score.precision_loss == 1


def test_wrong_target_content_does_not_count_as_coverage() -> None:
    before = '<p data-chunk-id="target">20 days</p><p data-chunk-id="safe">Keep me</p>'
    after = '<p data-chunk-id="target">21 days</p><p data-chunk-id="safe">Keep me</p>'
    case = make_case(
        [
            {
                "scope_id": "only-target",
                "expected_change_ids": ["target"],
                "protected_ids": ["safe"],
                "required_after_fragments": {"target": ["22 days"]},
                "forbidden_after_fragments": {"target": ["20 days"]},
                "explanation": "The requested value is 22.",
            }
        ]
    )

    score = score_edit(case, before, after)

    assert score.intended_change_coverage == 0
    assert score.incorrect_expected_ids == ["target"]


def test_collateral_text_and_formatting_changes_are_counted() -> None:
    before = '<p data-chunk-id="target">Old</p><p data-chunk-id="safe">Keep me</p>'
    after = '<p data-chunk-id="target">New</p><p class="highlight" data-chunk-id="safe">Keep me</p>'
    case = make_case(
        [
            {
                "scope_id": "only-target",
                "expected_change_ids": ["target"],
                "protected_ids": ["safe"],
                "explanation": "Formatting outside the target is collateral.",
            }
        ]
    )

    score = score_edit(case, before, after)

    assert score.intended_change_coverage == 1
    assert score.collateral_damage_rate == 1
    assert score.changed_protected_ids == ["safe"]


def test_table_row_is_scored_as_one_nested_unit() -> None:
    before = """
    <table data-chunk-id="table"><tbody>
      <tr data-chunk-id="row-a"><td>A</td><td>10</td></tr>
      <tr data-chunk-id="row-b"><td>B</td><td>20</td></tr>
    </tbody></table>
    """
    after = before.replace("<td>A</td><td>10</td>", "<td>A</td><td>15</td>")
    case = make_case(
        [
            {
                "scope_id": "row-a-only",
                "expected_change_ids": ["row-a"],
                "protected_ids": ["row-b"],
                "required_after_fragments": {"row-a": ["15"]},
                "explanation": "The table parent is intentionally not a protected unit.",
            }
        ]
    )

    score = score_edit(case, before, after)

    assert score.intended_change_coverage == 1
    assert score.collateral_damage_rate == 0


def test_ambiguous_instruction_uses_best_documented_scope() -> None:
    before = '<p data-chunk-id="a">30 days</p><p data-chunk-id="b">60 days</p>'
    after = '<p data-chunk-id="a">45 days</p><p data-chunk-id="b">60 days</p>'
    case = make_case(
        [
            {
                "scope_id": "both",
                "expected_change_ids": ["a", "b"],
                "required_after_fragments": {"a": ["45 days"], "b": ["45 days"]},
                "explanation": "Both periods.",
            },
            {
                "scope_id": "a-only",
                "expected_change_ids": ["a"],
                "required_after_fragments": {"a": ["45 days"]},
                "explanation": "First period only.",
            },
        ]
    )

    score = score_edit(case, before, after)

    assert score.matched_scope_id == "a-only"
    assert score.intended_change_coverage == 1


def test_unexpected_new_chunk_is_collateral() -> None:
    before = '<p data-chunk-id="target">Old</p><p data-chunk-id="safe">Safe</p>'
    after = (
        '<p data-chunk-id="target">New</p><p data-chunk-id="safe">Safe</p>'
        '<p data-chunk-id="invented">Unrequested</p>'
    )
    case = make_case(
        [
            {
                "scope_id": "target-only",
                "expected_change_ids": ["target"],
                "protected_ids": ["safe"],
                "explanation": "No new section was requested.",
            }
        ]
    )

    score = score_edit(case, before, after)

    assert score.unexpected_added_ids == ["invented"]
    assert score.collateral_damage_rate == 0.5


def test_duplicate_chunk_ids_are_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate data-chunk-id"):
        extract_units('<p data-chunk-id="same">A</p><p data-chunk-id="same">B</p>')


def test_repository_corpus_is_valid() -> None:
    project = Path(__file__).resolve().parents[2]
    corpus_path = project / "corpus/cases.jsonl"
    documents = project / "corpus/documents"

    assert len(load_corpus(corpus_path)) == 13
    assert validate_corpus(corpus_path, documents) == []
