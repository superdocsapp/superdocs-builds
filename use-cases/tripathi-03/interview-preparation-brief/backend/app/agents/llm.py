"""LLM client factory and structured invocation helpers."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Awaitable, Callable, TypeVar

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.exceptions import LLMConfigurationError
from app.core.logging import get_logger
from app.utils.json_utils import (
    coerce_truncated_json_object,
    example_payload_for_schema,
    extract_failed_generation,
    parse_model,
    strip_code_fences,
)

logger = get_logger(__name__)
T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return "rate_limit" in text or "429" in text or "tokens per day" in text or "tpm" in text


def _rate_limit_wait_seconds(exc: BaseException, default: float = 65.0) -> float:
    match = re.search(r"try again in ([0-9]+(?:\.[0-9]+)?)s", str(exc), re.IGNORECASE)
    if match:
        return min(float(match.group(1)) + 2.0, 300.0)
    return default


async def _with_rate_limit_retry(
    operation: Callable[[], Awaitable[R]],
    *,
    label: str,
    attempts: int = 3,
) -> R:
    last_exc: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await operation()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if not _is_rate_limit_error(exc) or attempt >= attempts:
                raise
            wait_s = _rate_limit_wait_seconds(exc)
            logger.warning(
                "Rate limit on %s (attempt %s/%s). Waiting %.0fs then retrying.",
                label,
                attempt,
                attempts,
                wait_s,
            )
            await asyncio.sleep(wait_s)
    assert last_exc is not None
    raise last_exc


def get_chat_model(temperature: float = 0.0, *, json_mode: bool = False):
    """Return a LangChain chat model based on LLM_PROVIDER."""
    settings = get_settings()
    provider = settings.llm_provider

    if provider == "anthropic":
        if not settings.anthropic_api_key:
            raise LLMConfigurationError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.anthropic_model,
            api_key=settings.anthropic_api_key,
            temperature=temperature,
        )

    if provider == "groq":
        if not settings.groq_api_key:
            raise LLMConfigurationError(
                "GROQ_API_KEY is required when LLM_PROVIDER=groq. "
                "Get a free key at https://console.groq.com/"
            )
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": settings.groq_model,
            "api_key": settings.groq_api_key,
            "base_url": GROQ_BASE_URL,
            "temperature": temperature,
            "max_tokens": 2048,
        }
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        if not settings.gemini_api_key:
            raise LLMConfigurationError(
                "GEMINI_API_KEY is required when LLM_PROVIDER=gemini. "
                "Get a free key at https://aistudio.google.com/"
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.gemini_model,
            google_api_key=settings.gemini_api_key,
            temperature=temperature,
        )

    if provider == "openai":
        if not settings.openai_api_key:
            raise LLMConfigurationError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        from langchain_openai import ChatOpenAI

        kwargs = {
            "model": settings.openai_model,
            "api_key": settings.openai_api_key,
            "temperature": temperature,
        }
        if json_mode:
            kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}
        return ChatOpenAI(**kwargs)

    raise LLMConfigurationError(
        f"Unsupported LLM_PROVIDER={provider!r}. Use: openai, anthropic, groq, or gemini."
    )


def _message_content_to_str(content: Any) -> str:
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content)


async def _invoke_json_text(
    *,
    schema: type[T],
    system: str,
    user: str,
    temperature: float,
) -> T:
    settings = get_settings()
    use_json_mode = settings.llm_provider in {"groq", "openai"}
    example = example_payload_for_schema(schema)
    required_keys = list(schema.model_fields.keys())

    async def _call() -> T:
        model = get_chat_model(temperature=temperature, json_mode=use_json_mode)
        try:
            response = await model.ainvoke(
                [
                    SystemMessage(
                        content=(
                            f"{system}\n\n"
                            "Return ONLY one JSON object with real values for this task.\n"
                            "Do NOT return a JSON Schema, $defs, properties, or type definitions.\n"
                            f"Required keys: {required_keys}\n"
                            f"Shape example (replace with real content):\n{example}\n"
                            "Keep strings concise. No markdown fences."
                        )
                    ),
                    HumanMessage(content=user),
                ]
            )
            return parse_model(schema, _message_content_to_str(response.content))
        except Exception as exc:  # noqa: BLE001
            failed = extract_failed_generation(exc)
            if failed:
                salvaged = coerce_truncated_json_object(failed)
                if salvaged is not None:
                    logger.warning(
                        "Recovered truncated JSON for %s from failed_generation",
                        schema.__name__,
                    )
                    return parse_model(schema, salvaged)
            raise

    return await _with_rate_limit_retry(_call, label=f"json:{schema.__name__}")


async def _repair_json(
    *,
    schema: type[T],
    broken: str,
    temperature: float = 0.0,
) -> T:
    async def _call() -> T:
        model = get_chat_model(temperature=temperature, json_mode=True)
        response = await model.ainvoke(
            [
                SystemMessage(
                    content=(
                        "Fix the following into VALID JSON only. "
                        "Preserve keys/values as much as possible. "
                        "No markdown, no commentary."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Target schema name: {schema.__name__}\n\n"
                        f"Broken JSON:\n{strip_code_fences(broken)[:60000]}"
                    )
                ),
            ]
        )
        return parse_model(schema, _message_content_to_str(response.content))

    return await _with_rate_limit_retry(_call, label=f"repair:{schema.__name__}")


async def invoke_structured(
    *,
    schema: type[T],
    system: str,
    user: str,
    temperature: float = 0.0,
) -> T:
    """Invoke chat model and parse into a Pydantic schema."""
    settings = get_settings()
    logger.debug("Structured invoke schema=%s provider=%s", schema.__name__, settings.llm_provider)

    # Small Groq models often echo JSON Schema from with_structured_output.
    # Prefer example-shaped JSON first for groq.
    if settings.llm_provider == "groq":
        try:
            return await _invoke_json_text(
                schema=schema,
                system=system,
                user=user,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit_error(exc):
                raise
            logger.warning(
                "Groq example-JSON failed for %s (%s); trying structured fallbacks",
                schema.__name__,
                exc,
            )

    model = get_chat_model(temperature=temperature)

    if settings.llm_provider in {"groq", "openai"}:
        try:
            structured = model.with_structured_output(schema, method="json_mode")

            async def _json_mode_call() -> T:
                result = await structured.ainvoke(
                    [
                        SystemMessage(
                            content=(
                                f"{system}\n\n"
                                "Return valid JSON instance data only (real values). "
                                "Do NOT return JSON Schema, $defs, or properties. "
                                "Keep answers concise."
                            )
                        ),
                        HumanMessage(content=user),
                    ]
                )
                if isinstance(result, schema):
                    return result
                if isinstance(result, dict):
                    return parse_model(schema, result)
                return parse_model(schema, result)

            return await _with_rate_limit_retry(
                _json_mode_call,
                label=f"structured:{schema.__name__}",
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limit_error(exc):
                raise
            logger.warning(
                "json_mode structured output failed for %s (%s); trying text JSON",
                schema.__name__,
                exc,
            )

    try:
        structured = model.with_structured_output(schema)

        async def _tool_call() -> T:
            result = await structured.ainvoke(
                [
                    SystemMessage(content=system),
                    HumanMessage(content=user),
                ]
            )
            if isinstance(result, schema):
                return result
            if isinstance(result, dict):
                return parse_model(schema, result)
            return parse_model(schema, result)

        return await _with_rate_limit_retry(_tool_call, label=f"tool:{schema.__name__}")
    except Exception as primary_exc:  # noqa: BLE001
        if _is_rate_limit_error(primary_exc):
            raise
        logger.warning(
            "Structured output failed for %s (%s); falling back to JSON parse",
            schema.__name__,
            primary_exc,
        )

    try:
        return await _invoke_json_text(
            schema=schema,
            system=system,
            user=user,
            temperature=temperature,
        )
    except Exception as parse_exc:  # noqa: BLE001
        if _is_rate_limit_error(parse_exc):
            raise
        logger.warning(
            "JSON parse failed for %s (%s); attempting repair",
            schema.__name__,
            parse_exc,
        )
        compact_user = (
            f"{user}\n\n"
            "IMPORTANT: Return a smaller valid JSON object with real values. "
            "Never return a schema."
        )
        try:
            return await _invoke_json_text(
                schema=schema,
                system=system,
                user=compact_user,
                temperature=0.0,
            )
        except Exception as second_exc:  # noqa: BLE001
            if _is_rate_limit_error(second_exc):
                raise
            broken = str(second_exc)
            if "Broken" in broken or len(broken) > 200:
                try:
                    return await _repair_json(schema=schema, broken=broken)
                except Exception:  # noqa: BLE001
                    pass
            raise ValueError(
                f"Failed to parse structured output for {schema.__name__}: {parse_exc}"
            ) from parse_exc


async def invoke_text(*, system: str, user: str, temperature: float = 0.0) -> str:
    async def _call() -> str:
        model = get_chat_model(temperature=temperature)
        response = await model.ainvoke(
            [
                SystemMessage(content=system),
                HumanMessage(content=user),
            ]
        )
        return _message_content_to_str(response.content).strip()

    return await _with_rate_limit_retry(_call, label="invoke_text")
