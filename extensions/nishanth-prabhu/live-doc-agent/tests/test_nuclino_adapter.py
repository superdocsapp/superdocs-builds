"""Tests verifying NuclinoWikiAdapter integration, patching, and 409 conflict responses."""

import pytest
from live_doc_agent.models import ConflictError, Patch
from live_doc_agent.wiki.nuclino import NuclinoWikiAdapter

SAMPLE_NUCLINO_MD = """# Architecture Overview

## Backend

We use FastAPI with Python 3.11.

## Cache

We use Redis for session caching.
"""


def test_nuclino_fetch_and_patch_success():
    remote_state = {
        "id": "item-123",
        "title": "Architecture Overview",
        "content": SAMPLE_NUCLINO_MD,
        "contentVersion": 5,
    }

    def mock_nuclino(action: str, params: dict):
        if action == "fetch":
            return {"status": "success", "data": dict(remote_state)}
        if action == "patch":
            assert params["payload"]["contentVersion"] == 5
            remote_state["content"] = params["payload"]["content"]
            remote_state["contentVersion"] = 6
            return {"status": "success", "data": dict(remote_state)}
        return {}

    adapter = NuclinoWikiAdapter(mock_handler=mock_nuclino)

    # 1. Fetch
    doc = adapter.fetch_page("item-123")
    assert doc.doc_id == "item-123"
    assert doc.content_version == "5"
    assert len(doc.sections) == 3
    section_titles = [s.title for s in doc.sections]
    assert "Backend" in section_titles
    assert "Cache" in section_titles

    # 2. Apply surgical patch
    patch = Patch(
        patch_id="p1",
        target_section="Backend",
        original_snippet="We use FastAPI with Python 3.11.",
        replacement_snippet="We use FastAPI with Python 3.12.",
        expected_version="5",
    )

    updated_doc = adapter.apply_patch("item-123", patch)
    assert updated_doc.content_version == "6"
    assert "Python 3.12" in updated_doc.content
    assert "We use Redis for session caching." in updated_doc.content


def test_nuclino_409_conflict_on_stale_version():
    remote_state = {
        "id": "item-123",
        "title": "Architecture Overview",
        "content": SAMPLE_NUCLINO_MD,
        "contentVersion": 10,
    }

    def mock_nuclino(action: str, params: dict):
        if action == "fetch":
            return {"status": "success", "data": dict(remote_state)}
        return {}

    adapter = NuclinoWikiAdapter(mock_handler=mock_nuclino)

    patch_with_stale_version = Patch(
        patch_id="p1",
        target_section="Backend",
        original_snippet="We use FastAPI with Python 3.11.",
        replacement_snippet="We use FastAPI with Python 3.12.",
        expected_version="9",  # Stale! Current is 10
    )

    with pytest.raises(ConflictError) as exc_info:
        adapter.apply_patch("item-123", patch_with_stale_version)

    assert "version mismatch" in str(exc_info.value).lower()
