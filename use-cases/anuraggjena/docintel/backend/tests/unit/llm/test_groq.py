import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel, ValidationError
import json

from backend.core.llm.groq import GroqProvider
from backend.core.llm.provider import LLMMessage, LLMResponse


class PersonSchema(BaseModel):
    """Test schema for structured generation"""
    name: str
    age: int


@pytest.fixture
def groq_provider():
    """Create GroqProvider with mocked client"""
    provider = GroqProvider(api_key="test-api-key")
    provider.client = MagicMock()
    return provider


@pytest.mark.asyncio
async def test_generate_basic(groq_provider):
    """Test basic generation with mocked API response"""
    # Mock the API response
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = "Hello, world!"
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.usage.total_tokens = 10

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Call generate
    messages = [LLMMessage(role="user", content="Say hello")]
    response = await groq_provider.generate(messages, model="test-model")

    # Assertions
    assert response.content == "Hello, world!"
    assert response.model == "test-model"
    assert response.tokens_used == 10
    assert response.metadata["finish_reason"] == "stop"

    # Verify API was called correctly
    groq_provider.client.chat.completions.create.assert_called_once()
    call_kwargs = groq_provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "test-model"
    assert call_kwargs["messages"] == [{"role": "user", "content": "Say hello"}]
    assert call_kwargs["temperature"] == 0.7


@pytest.mark.asyncio
async def test_generate_with_max_tokens(groq_provider):
    """Test generation with max_tokens parameter"""
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = "Short response"
    mock_completion.choices[0].finish_reason = "length"
    mock_completion.usage.total_tokens = 50

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    messages = [LLMMessage(role="user", content="Test")]
    response = await groq_provider.generate(messages, model="test-model", max_tokens=50)

    assert response.content == "Short response"
    call_kwargs = groq_provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs["max_tokens"] == 50


@pytest.mark.asyncio
async def test_generate_structured(groq_provider):
    """Test structured generation with JSON parsing and schema validation"""
    # Mock successful JSON response
    json_response = json.dumps({"name": "Alice", "age": 30})
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = json_response
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.usage.total_tokens = 15

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Call generate_structured
    messages = [LLMMessage(role="user", content="Generate person data")]
    result = await groq_provider.generate_structured(
        messages,
        model="test-model",
        response_schema=PersonSchema
    )

    # Assertions
    assert isinstance(result, PersonSchema)
    assert result.name == "Alice"
    assert result.age == 30

    # Verify schema instruction was added
    call_kwargs = groq_provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_generate_structured_json_error(groq_provider):
    """Test structured generation handles JSON parsing errors"""
    # Mock invalid JSON response
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = "Not valid JSON!"
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.usage.total_tokens = 5

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Call generate_structured and expect ValueError
    messages = [LLMMessage(role="user", content="Generate person data")]

    with pytest.raises(ValueError, match="Failed to parse JSON response"):
        await groq_provider.generate_structured(
            messages,
            model="test-model",
            response_schema=PersonSchema
        )


@pytest.mark.asyncio
async def test_generate_structured_validation_error(groq_provider):
    """Test structured generation handles schema validation errors"""
    # Mock JSON that doesn't match schema
    json_response = json.dumps({"name": "Bob", "age": "not-a-number"})
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = json_response
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.usage.total_tokens = 10

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    # Call generate_structured and expect ValueError
    messages = [LLMMessage(role="user", content="Generate person data")]

    with pytest.raises(ValueError, match="Response does not match schema"):
        await groq_provider.generate_structured(
            messages,
            model="test-model",
            response_schema=PersonSchema
        )


@pytest.mark.asyncio
async def test_generate_error_handling_no_choices(groq_provider):
    """Test generation handles API response with no choices"""
    # Mock response with empty choices
    mock_completion = MagicMock()
    mock_completion.choices = []

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    messages = [LLMMessage(role="user", content="Test")]

    with pytest.raises(ValueError, match="API returned no completion choices"):
        await groq_provider.generate(messages, model="test-model")


@pytest.mark.asyncio
async def test_generate_error_handling_no_message(groq_provider):
    """Test generation handles API response with no message"""
    # Mock response with no message
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message = None

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    messages = [LLMMessage(role="user", content="Test")]

    with pytest.raises(ValueError, match="API returned no message in choice"):
        await groq_provider.generate(messages, model="test-model")


@pytest.mark.asyncio
async def test_generate_error_handling_none_content(groq_provider):
    """Test generation handles API response with None content"""
    # Mock response with None content
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = None
    mock_completion.choices[0].finish_reason = "stop"

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    messages = [LLMMessage(role="user", content="Test")]

    with pytest.raises(ValueError, match="None content"):
        await groq_provider.generate(messages, model="test-model")


@pytest.mark.asyncio
async def test_generate_error_handling_api_failure(groq_provider):
    """Test generation handles API call failures"""
    # Mock API failure
    groq_provider.client.chat.completions.create = AsyncMock(
        side_effect=Exception("API connection error")
    )

    messages = [LLMMessage(role="user", content="Test")]

    with pytest.raises(Exception, match="API connection error"):
        await groq_provider.generate(messages, model="test-model")


@pytest.mark.asyncio
async def test_generate_with_no_usage_info(groq_provider):
    """Test generation handles missing usage info"""
    # Mock response without usage info
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock()]
    mock_completion.choices[0].message.content = "Response"
    mock_completion.choices[0].finish_reason = "stop"
    mock_completion.usage = None

    groq_provider.client.chat.completions.create = AsyncMock(return_value=mock_completion)

    messages = [LLMMessage(role="user", content="Test")]
    response = await groq_provider.generate(messages, model="test-model")

    assert response.tokens_used == 0
