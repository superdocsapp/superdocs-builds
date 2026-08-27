"""Integration tests for RevisionPipeline (mocked API)."""

import httpx
import pytest
import respx

from build_a.apparatus import RevisionMetadata
from build_a.client import SuperDocsClient
from build_a.pipeline import RevisionPipeline

SAMPLE_HTML = """<html><body>
<p id="p1">First paragraph.</p>
<p id="p2">Second paragraph.</p>
<p id="p3">Third paragraph.</p>
</body></html>"""

EDITED_HTML = """<html><body>
<p id="p1">First paragraph.</p>
<p id="p2">Second paragraph has been updated.</p>
<p id="p3">Third paragraph.</p>
<p id="p4">Brand new paragraph added.</p>
</body></html>"""


def _mock_chat_sequence(*responses: dict) -> None:
    """Register a sequence of mock responses for POST /v1/chat.

    Pipeline now combines load+edit into 1 call, then apparatus(N).
    Provide enough responses to cover all calls.
    """
    respx.post("https://api.superdocs.app/v1/chat").mock(
        side_effect=[httpx.Response(200, json=r) for r in responses]
    )


def _mock_chat_repeating(response: dict) -> None:
    """Register a single mock response that repeats for all calls."""
    respx.post("https://api.superdocs.app/v1/chat").mock(
        return_value=httpx.Response(200, json=response)
    )


def _mock_chat_error(status_code: int, error_body: dict) -> None:
    """Register a single error response for POST /v1/chat."""
    respx.post("https://api.superdocs.app/v1/chat").mock(
        return_value=httpx.Response(status_code, json=error_body)
    )


@pytest.mark.asyncio
@respx.mock
async def test_sync_flow_end_to_end() -> None:
    """Full sync flow: load+edit -> diff -> inject apparatus."""
    _mock_chat_sequence(
        # Step 1: combined load+edit
        {"response": "Edit applied", "session_id": "test-revision", "document_changes": {
            "updated_html": EDITED_HTML
        }},
        # Step 2+: apparatus injections — record+highlights batch
        {"response": "Apparatus injected", "session_id": "test-revision", "document_changes": None},
        # Step 3: change-bars batch
        {"response": "Change bars added", "session_id": "test-revision", "document_changes": None},
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["Updated section 4.2", "Added new paragraph"],
            highlights_summary="Safety threshold increased",
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-revision",
            edit_instructions="Update section 4.2 with new safety threshold",
            metadata=metadata,
        )

        assert result.success
        assert result.diff.has_changes
        assert len(result.diff.changed) > 0
        assert len(result.apparatus_instructions) > 0
        assert result.ops_used > 0


@pytest.mark.asyncio
@respx.mock
async def test_no_changes_skips_apparatus() -> None:
    """When edit produces no changes, apparatus injection is skipped."""
    _mock_chat_sequence(
        # Step 1: combined load+edit returns same HTML (no changes)
        {"response": "No changes needed", "session_id": "test-no-changes",
         "document_changes": {"updated_html": SAMPLE_HTML}},
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["No changes"],
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-no-changes",
            edit_instructions="Make no changes",
            metadata=metadata,
        )

        assert result.success
        assert not result.diff.has_changes
        assert len(result.apparatus_instructions) == 0


@pytest.mark.asyncio
@respx.mock
async def test_session_load_failure_returns_error() -> None:
    """When session load fails, pipeline returns error without proceeding."""
    _mock_chat_error(401, {"error": "Unauthorized"})
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=[],
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-fail",
            edit_instructions="Edit",
            metadata=metadata,
        )

        assert not result.success
        assert len(result.errors) > 0
        assert "Step 1" in result.errors[0]


@pytest.mark.asyncio
@respx.mock
async def test_metadata_in_instruction_content() -> None:
    """Verify revision number and date appear in generated instructions."""
    _mock_chat_sequence(
        {"response": "Edit applied", "session_id": "test-metadata",
         "document_changes": {"updated_html": EDITED_HTML}},
        {"response": "Apparatus injected", "session_id": "test-metadata", "document_changes": None},
        {"response": "Change bars added", "session_id": "test-metadata", "document_changes": None},
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0099",
            date="2025-06-01",
            changes=["Critical fix"],
            highlights_summary="Emergency patch",
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-metadata",
            edit_instructions="Apply critical fix",
            metadata=metadata,
        )

        all_text = " ".join(result.apparatus_instructions)
        assert "0099" in all_text
        assert "2025-06-01" in all_text
        assert "Critical fix" in all_text
        assert "Emergency patch" in all_text


@pytest.mark.asyncio
@respx.mock
async def test_tracker_counts_ops() -> None:
    """Pipeline run increments the client's operation tracker."""
    _mock_chat_sequence(
        {"response": "Done", "session_id": "test-ops",
         "document_changes": {"updated_html": EDITED_HTML}},
        {"response": "Apparatus injected", "session_id": "test-ops", "document_changes": None},
        {"response": "Change bars added", "session_id": "test-ops", "document_changes": None},
    )
    async with SuperDocsClient(api_key="sk_test_key") as client:
        pipeline = RevisionPipeline(client)
        metadata = RevisionMetadata(
            revision_number="0042",
            date="2025-01-15",
            changes=["Change 1"],
        )

        result = await pipeline.run(
            document_html=SAMPLE_HTML,
            session_id="test-ops",
            edit_instructions="Edit",
            metadata=metadata,
        )

        # 1 (load+edit combined) + N (apparatus injections)
        assert result.ops_used >= 1
        assert client.tracker.total_ops >= 1
