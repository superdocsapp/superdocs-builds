import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from backend.core.knowledge.stages import KnowledgeRetrieveStage, KnowledgeStoreStage


def make_engine():
    engine = AsyncMock()
    return engine


@pytest.mark.asyncio
async def test_retrieve_no_workspace_returns_empty():
    stage = KnowledgeRetrieveStage(make_engine(), "tariff")
    result = await stage.execute({})
    assert result["prior_knowledge"] == ""
    assert result["prior_knowledge_entries"] == []


@pytest.mark.asyncio
async def test_retrieve_loads_context():
    engine = make_engine()
    engine.retrieve_as_context = AsyncMock(return_value="Prior relevant knowledge:\n1. [claim] Widget A")
    entry = MagicMock()
    entry.id = uuid4()
    engine.retrieve = AsyncMock(return_value=[entry])

    stage = KnowledgeRetrieveStage(engine, "tariff")
    result = await stage.execute({"workspace_id": str(uuid4())})

    assert "Widget A" in result["prior_knowledge"]
    assert len(result["prior_knowledge_entries"]) == 1


@pytest.mark.asyncio
async def test_retrieve_with_tags():
    engine = make_engine()
    engine.retrieve_as_context = AsyncMock(return_value="context")
    engine.retrieve = AsyncMock(return_value=[])

    stage = KnowledgeRetrieveStage(engine, "tariff", tags_key="product_tags")
    await stage.execute({"workspace_id": str(uuid4()), "product_tags": ["electronics"]})

    call_kwargs = engine.retrieve_as_context.call_args.kwargs
    assert call_kwargs["tags"] == ["electronics"]


@pytest.mark.asyncio
async def test_retrieve_engine_error_returns_empty():
    engine = make_engine()
    engine.retrieve_as_context = AsyncMock(side_effect=Exception("DB down"))

    stage = KnowledgeRetrieveStage(engine, "tariff")
    result = await stage.execute({"workspace_id": str(uuid4())})
    assert result["prior_knowledge"] == ""


@pytest.mark.asyncio
async def test_store_no_workspace_returns_zero():
    stage = KnowledgeStoreStage(make_engine(), "tariff")
    result = await stage.execute({})
    assert result["knowledge_stored"] == 0


@pytest.mark.asyncio
async def test_store_claims_and_output():
    engine = make_engine()
    entry = MagicMock()
    entry.id = uuid4()
    engine.store = AsyncMock(return_value=entry)

    stage = KnowledgeStoreStage(engine, "tariff")
    state = {
        "workspace_id": str(uuid4()),
        "workflow_run_id": str(uuid4()),
        "claims": [
            {"content": "HS code 8471.30", "confidence_score": 0.9, "tags": ["electronics"]},
            {"content": "Duty rate 0%"},
        ],
        "generated_output": "Full tariff analysis report"
    }
    result = await stage.execute(state)
    # 2 claims + 1 output = 3 stores
    assert result["knowledge_stored"] == 3
    assert engine.store.call_count == 3


@pytest.mark.asyncio
async def test_store_skips_empty_content():
    engine = make_engine()
    engine.store = AsyncMock(return_value=MagicMock())

    stage = KnowledgeStoreStage(engine, "tariff")
    state = {
        "workspace_id": str(uuid4()),
        "claims": [{"content": ""}],  # empty content should be skipped
        "generated_output": ""
    }
    result = await stage.execute(state)
    assert result["knowledge_stored"] == 0
    assert not engine.store.called
