from edit_precision_evaluator.alignment import align_chunk_ids, remap_case
from edit_precision_evaluator.models import CorpusCase


def test_regenerated_upload_ids_are_aligned_before_editing() -> None:
    original = (
        '<h2 data-chunk-id="old-heading">Policy</h2>'
        '<p data-chunk-id="old-target">Change 20 days</p>'
        '<p data-chunk-id="old-safe">Keep this</p>'
    )
    uploaded = (
        '<h2 data-chunk-id="new-1">Policy</h2>'
        '<p data-chunk-id="new-2">Change 20 days</p>'
        '<p data-chunk-id="new-3">Keep this</p>'
    )

    mapping = align_chunk_ids(original, uploaded, {"old-target", "old-safe"})

    assert mapping == {"old-target": "new-2", "old-safe": "new-3"}


def test_label_assertions_are_remapped_without_entering_the_prompt() -> None:
    case = CorpusCase.model_validate(
        {
            "case_id": "case",
            "document": "doc.html",
            "instruction": "Change target",
            "instruction_type": "single_sentence",
            "label_rationale": "Fixture",
            "labeler": "test",
            "acceptable_scopes": [
                {
                    "scope_id": "scope",
                    "expected_change_ids": ["old-target"],
                    "protected_ids": ["old-safe"],
                    "required_after_fragments": {"old-target": ["New"]},
                    "forbidden_after_fragments": {"old-target": ["Old"]},
                    "explanation": "Fixture",
                }
            ],
        }
    )

    remapped = remap_case(case, {"old-target": "new-target", "old-safe": "new-safe"})
    scope = remapped.acceptable_scopes[0]

    assert scope.expected_change_ids == {"new-target"}
    assert scope.protected_ids == {"new-safe"}
    assert scope.required_after_fragments == {"new-target": ["New"]}
    assert case.instruction == remapped.instruction
