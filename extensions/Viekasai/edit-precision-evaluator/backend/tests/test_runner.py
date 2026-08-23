from pathlib import Path

import pytest

from edit_precision_evaluator.budget import OperationBudget
from edit_precision_evaluator.models import Approach, CorpusCase
from edit_precision_evaluator.runner import run_case
from edit_precision_evaluator.superdocs_client import (
    ExportedDocument,
    SuperDocsOutcome,
    UploadedDocument,
)


@pytest.mark.asyncio
async def test_search_uses_disposable_session_and_cannot_contaminate_edit(tmp_path: Path) -> None:
    before = '<p data-chunk-id="target">Old</p><p data-chunk-id="safe">Keep</p>'
    after = '<p data-chunk-id="target">New</p><p data-chunk-id="safe">Keep</p>'
    contaminated_search = (
        '<p data-chunk-id="target">Search changed this</p>'
        '<p data-chunk-id="safe">Search changed this too</p>'
    )
    case = CorpusCase.model_validate(
        {
            "case_id": "isolation",
            "document": "doc.html",
            "instruction": "Change Old to New",
            "instruction_type": "single_sentence",
            "label_rationale": "Fixture",
            "labeler": "test",
            "acceptable_scopes": [
                {
                    "scope_id": "target-only",
                    "expected_change_ids": ["target"],
                    "protected_ids": ["safe"],
                    "required_after_fragments": {"target": ["New"]},
                    "explanation": "Only target changes",
                }
            ],
        }
    )

    class FakeClient:
        analyze_session = ""
        edit_session = ""

        async def upload_document(self, *, filename: str, content: bytes, session_id: str):
            return UploadedDocument(html=content.decode(), filename=filename)

        async def analyze(self, *, document_html, message: str, session_id: str):
            self.analyze_session = session_id
            return SuperDocsOutcome(
                updated_html=contaminated_search,
                response_text='{"chunk_ids":["target"]}',
                operations_charged=1,
            )

        async def edit_with_approval(self, *, document_html, message: str, session_id: str):
            self.edit_session = session_id
            return SuperDocsOutcome(
                updated_html=after,
                response_text="Done",
                operations_charged=1,
            )

        async def export_document(self, *, session_id: str, filename: str, format: str):
            return ExportedDocument(content=b"export", content_type="text/html")

    client = FakeClient()
    result = await run_case(
        client=client,
        budget=OperationBudget(2),
        case=case,
        document_html=before,
        approach=Approach.SEARCH_SCOPED,
        run_id="test",
        export_root=tmp_path,
    )

    assert client.analyze_session.endswith("-retrieval")
    assert client.analyze_session != client.edit_session
    assert result.search_chunk_ids == ["target"]
    assert result.score.intended_change_coverage == 1
    assert result.score.collateral_damage_rate == 0
    assert result.operations_used == 2
