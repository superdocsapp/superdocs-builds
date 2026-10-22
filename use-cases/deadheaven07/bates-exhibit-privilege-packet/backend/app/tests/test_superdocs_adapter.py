import json

import pytest

from app.services.superdocs_adapter import SuperDocsRESTAdapter
from app.services.superdocs_port import ProposedChange, ProposedChangeBatch


class TestSuperDocsProposedChangeParsing:
    @pytest.fixture
    def adapter(self):
        return SuperDocsRESTAdapter()

    def test_parse_proposed_change_batch_single_change(self, adapter):
        inner_content = {
            "type": "single_approval",
            "batch_id": "ch_1",
            "batch_total": 1,
            "changes": [
                {
                    "change_id": "ch_1",
                    "operation": "edit",
                    "chunk_id": "chunk-123",
                    "old_html": "<p>Original text</p>",
                    "new_html": "<p>Updated text</p>",
                    "ai_explanation": "Updated for clarity",
                    "insert_after_chunk_id": None,
                    "document_id": "doc-456",
                }
            ],
            "awaiting_kind": "approval",
        }

        outer_content = {
            "type": "proposed_change_batch",
            "content": json.dumps(inner_content),
            "sequence": 1,
        }

        content = json.dumps(outer_content)
        result = adapter.parse_proposed_change_batch(content)

        assert isinstance(result, ProposedChangeBatch)
        assert result.batch_id == "ch_1"
        assert result.batch_total == 1
        assert result.awaiting_kind == "approval"
        assert len(result.changes) == 1

        change = result.changes[0]
        assert isinstance(change, ProposedChange)
        assert change.change_id == "ch_1"
        assert change.operation == "edit"
        assert change.chunk_id == "chunk-123"
        assert change.old_html == "<p>Original text</p>"
        assert change.new_html == "<p>Updated text</p>"
        assert change.ai_explanation == "Updated for clarity"
        assert change.document_id == "doc-456"

    def test_parse_proposed_change_batch_multiple_changes(self, adapter):
        inner_content = {
            "type": "batch_approval",
            "batch_id": "ch_1",
            "batch_total": 3,
            "changes": [
                {
                    "change_id": "ch_1",
                    "operation": "edit",
                    "chunk_id": "chunk-1",
                    "old_html": "<p>Old 1</p>",
                    "new_html": "<p>New 1</p>",
                    "ai_explanation": "Change 1",
                    "insert_after_chunk_id": None,
                },
                {
                    "change_id": "ch_2",
                    "operation": "create",
                    "chunk_id": None,
                    "old_html": None,
                    "new_html": "<p>New section</p>",
                    "ai_explanation": "Adding new section",
                    "insert_after_chunk_id": "chunk-1",
                },
                {
                    "change_id": "ch_3",
                    "operation": "delete",
                    "chunk_id": "chunk-2",
                    "old_html": "<p>To delete</p>",
                    "new_html": None,
                    "ai_explanation": "Removing obsolete section",
                    "insert_after_chunk_id": None,
                },
            ],
            "awaiting_kind": "approval",
        }

        outer_content = {
            "type": "proposed_change_batch",
            "content": json.dumps(inner_content),
            "sequence": 2,
        }

        content = json.dumps(outer_content)
        result = adapter.parse_proposed_change_batch(content)

        assert result.batch_total == 3
        assert len(result.changes) == 3

        assert result.changes[0].operation == "edit"
        assert result.changes[1].operation == "create"
        assert result.changes[2].operation == "delete"

    def test_parse_proposed_change_batch_continue_prompt(self, adapter):
        inner_content = {
            "type": "batch_approval",
            "batch_id": "ch_1",
            "batch_total": 1,
            "changes": [],
            "awaiting_kind": "continue_prompt",
            "continue_prompt": {
                "message": "I've updated 500 of 864 sections. 364 remain. Continue?",
                "done": 500,
                "total": 864,
                "remaining": 364,
            },
        }

        outer_content = {
            "type": "proposed_change_batch",
            "content": json.dumps(inner_content),
            "sequence": 3,
        }

        content = json.dumps(outer_content)
        result = adapter.parse_proposed_change_batch(content)

        assert result.awaiting_kind == "continue_prompt"
        assert result.continue_prompt is not None
        assert result.continue_prompt["done"] == 500
        assert result.continue_prompt["total"] == 864

    def test_parse_proposed_change_batch_invalid_json(self, adapter):
        with pytest.raises(ValueError):
            adapter.parse_proposed_change_batch("not valid json")

    def test_parse_proposed_change_batch_missing_content(self, adapter):
        outer_content = {
            "type": "proposed_change_batch",
            "sequence": 1,
        }
        content = json.dumps(outer_content)

        with pytest.raises(ValueError):
            adapter.parse_proposed_change_batch(content)

    def test_parse_proposed_change_batch_missing_changes(self, adapter):
        inner_content = {
            "type": "batch_approval",
            "batch_id": "ch_1",
            "batch_total": 0,
        }
        outer_content = {
            "type": "proposed_change_batch",
            "content": json.dumps(inner_content),
            "sequence": 1,
        }
        content = json.dumps(outer_content)

        result = adapter.parse_proposed_change_batch(content)
        assert result.batch_total == 0
        assert len(result.changes) == 0
