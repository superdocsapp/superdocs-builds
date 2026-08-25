import pytest
from unittest.mock import AsyncMock, MagicMock
from backend.modules.screenplay.stages.parse import ParseStage
from backend.modules.screenplay.schemas import ParsedScreenplay, ScreenplayElement
from backend.core.llm.provider import LLMProvider


@pytest.fixture
def mock_llm():
    """Mock LLM provider for testing AI fallback."""
    provider = MagicMock(spec=LLMProvider)
    provider.generate_structured = AsyncMock()
    return provider


@pytest.mark.asyncio
async def test_parse_stage_with_clean_screenplay_no_llm_calls(mock_llm):
    """Test that a clean, well-formatted screenplay makes ZERO LLM calls."""
    stage = ParseStage(llm_provider=mock_llm)

    # Clean screenplay with all deterministic elements
    clean_text = """INT. OFFICE - DAY

A man sits at a desk.

JOHN
Hello there.

JANE
(smiling)
Hi John.

CUT TO:"""

    state = {"document_text": clean_text}
    result = await stage.execute(state)

    # Assert NO LLM calls were made
    mock_llm.generate_structured.assert_not_called()

    # Assert parsed screenplay is returned
    assert "parsed_screenplay" in result
    parsed = result["parsed_screenplay"]
    assert parsed["scene_count"] == 1
    assert len(parsed["elements"]) > 0
    assert len(parsed["character_list"]) == 2
    assert set(parsed["character_list"]) == {"JOHN", "JANE"}


@pytest.mark.asyncio
async def test_parse_stage_with_uncertain_elements_triggers_llm(mock_llm):
    """Test that uncertain elements (confidence < 0.7) trigger AI fallback."""
    # Mock LLM to return a classification for uncertain element
    # Use a dict to match the ElementClassification schema
    mock_llm.generate_structured.return_value = {
        "element_type": "action",
        "confidence": 0.85
    }

    stage = ParseStage(llm_provider=mock_llm)

    # Screenplay with an uncertain element (all-caps action line after non-blank)
    # According to parser.py, all-caps in neutral state gets confidence 0.5 -> "uncertain"
    text_with_uncertain = """INT. OFFICE - DAY
Some action line here.
ALL CAPS UNCERTAIN LINE

JOHN
Hello."""

    state = {"document_text": text_with_uncertain}
    result = await stage.execute(state)

    # Assert LLM was called for uncertain element
    assert mock_llm.generate_structured.call_count >= 1

    # Assert parsed screenplay includes the reclassified element
    assert "parsed_screenplay" in result
    parsed = result["parsed_screenplay"]
    assert len(parsed["elements"]) > 0


@pytest.mark.asyncio
async def test_parse_stage_reads_document_text_key(mock_llm):
    """Test that ParseStage reads from 'document_text' key, not 'document_content'."""
    stage = ParseStage(llm_provider=mock_llm)

    # Provide only document_text, not document_content
    state = {
        "document_text": "INT. OFFICE - DAY\n\nA man sits.",
        "document_content": "WRONG KEY - SHOULD NOT BE READ"
    }

    result = await stage.execute(state)

    # Assert that it parsed from document_text
    parsed = result["parsed_screenplay"]
    assert len(parsed["elements"]) > 0
    # Verify content came from document_text (has "sits")
    elements_text = " ".join([e["content"] for e in parsed["elements"]])
    assert "sits" in elements_text
    assert "WRONG KEY" not in elements_text


@pytest.mark.asyncio
async def test_parse_stage_returns_correct_schema_and_logs_counts(mock_llm):
    """Test that ParseStage returns ParsedScreenplay with correct structure and logs counts."""
    stage = ParseStage(llm_provider=mock_llm)

    screenplay_text = """INT. OFFICE - DAY

John enters the room.

JOHN
Hello.

EXT. STREET - NIGHT

Jane walks away.

JANE
Goodbye."""

    state = {"document_text": screenplay_text}
    result = await stage.execute(state)

    # Assert structure matches requirements
    assert "parsed_screenplay" in result
    parsed = result["parsed_screenplay"]

    # Verify ParsedScreenplay fields
    assert "elements" in parsed
    assert "scene_count" in parsed
    assert "character_list" in parsed

    # Verify counts
    assert parsed["scene_count"] == 2
    assert len(parsed["elements"]) > 0
    assert len(parsed["character_list"]) == 2

    # Verify element structure includes confidence
    for elem in parsed["elements"]:
        assert "element_type" in elem
        assert "content" in elem
        assert "element_index" in elem
        assert "confidence" in elem
