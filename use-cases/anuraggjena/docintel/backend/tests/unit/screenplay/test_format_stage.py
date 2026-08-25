import pytest
from unittest.mock import MagicMock, AsyncMock
from uuid import uuid4
from backend.modules.screenplay.schemas import ParsedScreenplay, ScreenplayElement


def _make_parsed(elements):
    ps = ParsedScreenplay(
        elements=elements,
        scene_count=1,
        character_list=[],
    )
    return ps.model_dump()


def _make_state(parsed_dict):
    return {
        "workflow_run_id": str(uuid4()),
        "workspace_id": str(uuid4()),
        "document_id": str(uuid4()),
        "parsed_screenplay": parsed_dict,
        "document_text": "",
    }


@pytest.mark.asyncio
async def test_format_stage_produces_formatting_items():
    from backend.modules.screenplay.stages.format import FormatStage
    from backend.core.llm.provider import LLMProvider
    from backend.repositories.screenplay import FormattingItemRepository

    mock_llm = MagicMock(spec=LLMProvider)
    mock_repo = AsyncMock(spec=FormattingItemRepository)

    item_mock = MagicMock()
    item_mock.id = uuid4()
    mock_repo.create = AsyncMock(return_value=item_mock)

    elements = [
        ScreenplayElement(element_type="scene_heading", content="int. office - day",
                          element_index=0, scene_number=1, confidence=1.0),
        ScreenplayElement(element_type="action", content="A man enters.",
                          element_index=1, confidence=1.0),
    ]
    state = _make_state(_make_parsed(elements))

    stage = FormatStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute(state)

    assert "formatting_items" in result
    items = result["formatting_items"]
    assert len(items) == 2
    # Scene heading should be uppercased
    scene_item = next(i for i in items if i["element_type"] == "scene_heading")
    assert scene_item["formatted_text"] == "INT. OFFICE - DAY"
    assert scene_item["change_type"] == "capitalization"


@pytest.mark.asyncio
async def test_format_stage_preserves_dialogue():
    from backend.modules.screenplay.stages.format import FormatStage
    from backend.core.llm.provider import LLMProvider
    from backend.repositories.screenplay import FormattingItemRepository

    mock_llm = MagicMock(spec=LLMProvider)
    mock_repo = AsyncMock(spec=FormattingItemRepository)
    mock_repo.create = AsyncMock(return_value=MagicMock(id=uuid4()))

    elements = [
        ScreenplayElement(element_type="dialogue", content="Hello there.",
                          element_index=0, character_name="JOHN", confidence=1.0),
    ]
    state = _make_state(_make_parsed(elements))

    stage = FormatStage(llm_provider=mock_llm, formatting_item_repo=mock_repo)
    result = await stage.execute(state)

    items = result["formatting_items"]
    dia = items[0]
    assert dia["formatted_text"] == "Hello there."
    assert dia["change_type"] == "no_change"
    assert not dia["content_drift"]
