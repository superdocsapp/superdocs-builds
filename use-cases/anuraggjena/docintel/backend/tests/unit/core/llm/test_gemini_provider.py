"""Unit tests for GeminiProvider structured output, native schema enforcement, retry, and diagnostics."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import BaseModel, Field

from backend.core.llm.gemini import GeminiProvider, _extract_json_str, _safe_lines_preview, _get_google_genai_version
from backend.core.llm.provider import LLMMessage, LLMResponse
from backend.modules.tariff.memo_types import MemoSectionOutput


class SampleSchema(BaseModel):
    product_name: str
    hs_code: str = Field(description="Harmonized System Code")
    confidence: float = 1.0


def _make_gemini_response(content: str, total_tokens: int = 42, finish_reason: str = "STOP", parsed=None):
    part = MagicMock()
    part.text = content
    candidate = MagicMock()
    candidate.content = MagicMock()
    candidate.content.parts = [part]
    candidate.finish_reason = finish_reason

    resp = MagicMock()
    resp.candidates = [candidate]
    resp.usage_metadata = MagicMock()
    resp.usage_metadata.total_token_count = total_tokens
    resp.parsed = parsed
    resp.text = content
    return resp


@pytest.fixture
def provider():
    with patch("google.genai.Client"):
        p = GeminiProvider(api_key="test-api-key", models=["gemini-2.5-flash", "gemini-2.5-pro"])
        p.client = MagicMock()
        p.client.aio = MagicMock()
        p.client.aio.models = MagicMock()
        return p


def test_extract_json_str_clean_json():
    raw = '{"product_name": "Drone", "hs_code": "8806.24.00"}'
    assert _extract_json_str(raw) == raw


def test_extract_json_str_markdown_fences():
    raw = '```json\n{"product_name": "Drone", "hs_code": "8806.24.00"}\n```'
    assert _extract_json_str(raw) == '{"product_name": "Drone", "hs_code": "8806.24.00"}'


def test_extract_json_str_with_preamble_and_postamble():
    raw = 'Here is your structured JSON output:\n{"product_name": "Drone", "hs_code": "8806.24.00"}\nHope this helps!'
    assert _extract_json_str(raw) == '{"product_name": "Drone", "hs_code": "8806.24.00"}'


def test_safe_lines_preview():
    lines = [f"line {i}" for i in range(1, 31)]
    text = "\n".join(lines)
    preview = _safe_lines_preview(text, 15, 24)
    preview_lines = preview.splitlines()
    assert len(preview_lines) == 10
    assert preview_lines[0] == "line 15"
    assert preview_lines[-1] == "line 24"


def test_get_google_genai_version():
    version = _get_google_genai_version()
    assert version != "unknown"
    assert len(version) > 0


@pytest.mark.asyncio
async def test_generate_structured_success_first_try(provider):
    payload = json.dumps({"product_name": "AeroLink X7", "hs_code": "8517.62.00", "confidence": 0.95})
    gemini_resp = _make_gemini_response(payload, total_tokens=120)
    provider.client.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    messages = [LLMMessage(role="user", content="Classify product")]
    result = await provider.generate_structured(
        messages=messages,
        model="gemini-2.5-flash",
        response_schema=SampleSchema,
    )

    assert isinstance(result, SampleSchema)
    assert result.product_name == "AeroLink X7"
    assert result.hs_code == "8517.62.00"
    assert result.confidence == 0.95

    # Verify native schema enforcement was passed in config
    call_kwargs = provider.client.aio.models.generate_content.call_args.kwargs
    gen_config = call_kwargs["config"]
    assert gen_config.response_mime_type == "application/json"
    assert gen_config.response_schema == SampleSchema


@pytest.mark.asyncio
async def test_generate_structured_uses_response_parsed_when_available(provider):
    expected_instance = SampleSchema(product_name="AeroLink X7", hs_code="8517.62.00", confidence=0.99)
    # response.text is intentionally empty/malformed, but response.parsed is populated by SDK
    gemini_resp = _make_gemini_response("invalid text string", parsed=expected_instance)
    provider.client.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Classify product")],
        model="gemini-3.1-flash-lite",
        response_schema=SampleSchema,
    )

    assert result is expected_instance
    assert result.product_name == "AeroLink X7"
    assert provider.client.aio.models.generate_content.call_count == 1


@pytest.mark.asyncio
async def test_generate_structured_uses_response_parsed_dict_when_available(provider):
    parsed_dict = {"product_name": "AeroLink X7", "hs_code": "8517.62.00", "confidence": 0.88}
    gemini_resp = _make_gemini_response("invalid text string", parsed=parsed_dict)
    provider.client.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Classify product")],
        model="gemini-3.1-flash-lite",
        response_schema=SampleSchema,
    )

    assert isinstance(result, SampleSchema)
    assert result.product_name == "AeroLink X7"
    assert result.confidence == 0.88


@pytest.mark.asyncio
async def test_production_configuration_with_memo_section_output(provider):
    output_instance = MemoSectionOutput(
        content="This is the executive summary.",
        analyst_reasoning="Based on Section XVI Note 3.",
    )
    gemini_resp = _make_gemini_response(output_instance.model_dump_json(), parsed=output_instance)
    provider.client.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Draft executive summary")],
        model="gemini-3.1-flash-lite",
        response_schema=MemoSectionOutput,
    )

    assert isinstance(result, MemoSectionOutput)
    assert result.content == "This is the executive summary."
    assert result.analyst_reasoning == "Based on Section XVI Note 3."

    # Verify exact GenerateContentConfig passed to client.aio.models.generate_content
    call_kwargs = provider.client.aio.models.generate_content.call_args.kwargs
    config = call_kwargs["config"]
    assert config.response_mime_type == "application/json"
    assert config.response_schema == MemoSectionOutput


@pytest.mark.asyncio
async def test_generate_structured_handles_markdown_wrapped_json(provider):
    payload = '```json\n{"product_name": "AeroLink X7", "hs_code": "8517.62.00"}\n```'
    gemini_resp = _make_gemini_response(payload)
    provider.client.aio.models.generate_content = AsyncMock(return_value=gemini_resp)

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Classify product")],
        model="gemini-2.5-flash",
        response_schema=SampleSchema,
    )

    assert isinstance(result, SampleSchema)
    assert result.product_name == "AeroLink X7"
    assert result.hs_code == "8517.62.00"


@pytest.mark.asyncio
async def test_generate_structured_retries_on_malformed_json_and_recovers(provider):
    bad_resp = _make_gemini_response("Not valid JSON at all")
    good_payload = json.dumps({"product_name": "AeroLink X7", "hs_code": "8517.62.00"})
    good_resp = _make_gemini_response(good_payload)

    provider.client.aio.models.generate_content = AsyncMock(side_effect=[bad_resp, good_resp])

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Classify product")],
        model="gemini-2.5-flash",
        response_schema=SampleSchema,
    )

    assert isinstance(result, SampleSchema)
    assert result.product_name == "AeroLink X7"
    assert provider.client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_generate_structured_retries_on_validation_error_and_recovers(provider):
    bad_payload = json.dumps({"wrong_field": "123"})
    bad_resp = _make_gemini_response(bad_payload)
    good_payload = json.dumps({"product_name": "AeroLink X7", "hs_code": "8517.62.00"})
    good_resp = _make_gemini_response(good_payload)

    provider.client.aio.models.generate_content = AsyncMock(side_effect=[bad_resp, good_resp])

    result = await provider.generate_structured(
        messages=[LLMMessage(role="user", content="Classify product")],
        model="gemini-2.5-flash",
        response_schema=SampleSchema,
    )

    assert isinstance(result, SampleSchema)
    assert result.product_name == "AeroLink X7"
    assert provider.client.aio.models.generate_content.call_count == 2


@pytest.mark.asyncio
async def test_generate_structured_raises_after_bounded_retry_exhaustion_with_diagnostics(provider):
    bad_resp = _make_gemini_response("Line 1\nLine 2\nLine 3\nLine 4\nLine 5\nLine 6\nLine 7\nLine 8\nLine 9\nLine 10\nLine 11\nLine 12\nLine 13\nLine 14\nLine 15\nLine 16\nLine 17\nLine 18\nLine 19\nLine 20 malformed text\nLine 21\nLine 22\nLine 23\nLine 24\nLine 25")
    provider.client.aio.models.generate_content = AsyncMock(return_value=bad_resp)

    with patch("backend.core.llm.gemini.logger") as mock_logger:
        with pytest.raises(Exception):
            await provider.generate_structured(
                messages=[LLMMessage(role="user", content="Classify product")],
                model="gemini-3.1-flash-lite",
                response_schema=SampleSchema,
            )

        assert provider.client.aio.models.generate_content.call_count == 2
        # Check diagnostic failure log was emitted
        mock_logger.warning.assert_any_call(
            "llm_generate_structured_diagnostic_failure",
            sdk_version=_get_google_genai_version(),
            model="gemini-3.1-flash-lite",
            schema="SampleSchema",
            response_schema_present=True,
            response_mime_type="application/json",
            response_parsed_populated=False,
            response_text_length=len(bad_resp.text),
            preview_lines_15_24=_safe_lines_preview(bad_resp.text, 15, 24),
            finish_reason="STOP",
            attempt=1,
            error=pytest.approx(mock_logger.warning.call_args_list[0][1].get("error") if mock_logger.warning.call_args_list else ""),
            error_type=pytest.approx(mock_logger.warning.call_args_list[0][1].get("error_type") if mock_logger.warning.call_args_list else ""),
        )
