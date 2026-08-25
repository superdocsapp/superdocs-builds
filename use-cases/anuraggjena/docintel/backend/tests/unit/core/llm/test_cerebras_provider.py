"""Unit tests for CerebrasProvider — RED phase before implementation."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel

from backend.core.llm.cerebras import CerebrasProvider
from backend.core.llm.provider import LLMMessage


class _Schema(BaseModel):
    answer: str
    confidence: float = 1.0


def _make_choice(content: str, finish_reason: str = "stop"):
    choice = MagicMock()
    choice.message = MagicMock()
    choice.message.content = content
    choice.finish_reason = finish_reason
    return choice


def _make_completion(content: str, total_tokens: int = 50):
    comp = MagicMock()
    comp.choices = [_make_choice(content)]
    comp.usage = MagicMock()
    comp.usage.total_tokens = total_tokens
    return comp


@pytest.fixture
def provider():
    return CerebrasProvider(api_key="test-key")


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_returns_llm_response(provider):
    comp = _make_completion("Hello world")
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    messages = [LLMMessage(role="user", content="Say hello")]
    resp = await provider.generate(messages, model="gpt-oss-120b")

    assert resp.content == "Hello world"
    assert resp.model == "gpt-oss-120b"
    assert resp.tokens_used == 50


@pytest.mark.asyncio
async def test_generate_passes_max_tokens(provider):
    comp = _make_completion("hi")
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    await provider.generate(
        [LLMMessage(role="user", content="hi")],
        model="gpt-oss-120b",
        max_tokens=512,
    )

    call_kwargs = provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs["max_tokens"] == 512


@pytest.mark.asyncio
async def test_generate_sets_json_mode_when_requested(provider):
    comp = _make_completion('{"key": "val"}')
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    class _AnySchema(BaseModel):
        key: str

    await provider.generate(
        [LLMMessage(role="user", content="return json")],
        model="gpt-oss-120b",
        response_format=_AnySchema,
    )

    call_kwargs = provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("response_format") == {"type": "json_object"}


@pytest.mark.asyncio
async def test_generate_raises_on_empty_choices(provider):
    comp = MagicMock()
    comp.choices = []
    comp.usage = MagicMock()
    comp.usage.total_tokens = 0
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    with pytest.raises(ValueError, match="no completion choices"):
        await provider.generate(
            [LLMMessage(role="user", content="hi")],
            model="gpt-oss-120b",
        )


# ---------------------------------------------------------------------------
# generate_structured()
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_generate_structured_returns_validated_model(provider):
    payload = json.dumps({"answer": "yes", "confidence": 0.9})
    comp = _make_completion(payload, total_tokens=80)
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    result = await provider.generate_structured(
        [LLMMessage(role="user", content="answer yes or no")],
        model="gpt-oss-120b",
        response_schema=_Schema,
    )

    assert isinstance(result, _Schema)
    assert result.answer == "yes"
    assert result.confidence == 0.9


@pytest.mark.asyncio
async def test_generate_structured_appends_schema_to_system(provider):
    payload = json.dumps({"answer": "ok", "confidence": 1.0})
    comp = _make_completion(payload)
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    messages = [
        LLMMessage(role="system", content="You are helpful."),
        LLMMessage(role="user", content="go"),
    ]
    await provider.generate_structured(messages, model="gpt-oss-120b", response_schema=_Schema)

    sent = provider.client.chat.completions.create.call_args.kwargs["messages"]
    system_content = sent[0]["content"]
    assert "json" in system_content.lower()
    assert "_Schema" in system_content or "answer" in system_content


@pytest.mark.asyncio
async def test_generate_structured_raises_on_invalid_json(provider):
    comp = _make_completion("not json at all")
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    with pytest.raises(ValueError, match="Failed to parse JSON"):
        await provider.generate_structured(
            [LLMMessage(role="user", content="go")],
            model="gpt-oss-120b",
            response_schema=_Schema,
        )


@pytest.mark.asyncio
async def test_generate_structured_raises_on_schema_mismatch(provider):
    payload = json.dumps({"wrong_field": 42})
    comp = _make_completion(payload)
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    with pytest.raises(ValueError, match="does not match schema"):
        await provider.generate_structured(
            [LLMMessage(role="user", content="go")],
            model="gpt-oss-120b",
            response_schema=_Schema,
        )


@pytest.mark.asyncio
async def test_generate_structured_accepts_max_tokens(provider):
    payload = json.dumps({"answer": "x", "confidence": 1.0})
    comp = _make_completion(payload)
    provider.client.chat.completions.create = AsyncMock(return_value=comp)

    await provider.generate_structured(
        [LLMMessage(role="user", content="go")],
        model="gpt-oss-120b",
        response_schema=_Schema,
        max_tokens=2048,
    )

    call_kwargs = provider.client.chat.completions.create.call_args.kwargs
    assert call_kwargs.get("max_tokens") == 2048
