import importlib.metadata
import json
import re
from typing import Any, Optional

from google import genai
from google.genai import types
from google.genai.errors import ClientError, ServerError
from pydantic import BaseModel, ValidationError

from backend.core.llm.provider import LLMProvider, LLMMessage, LLMResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

# HTTP status codes and gRPC status names that indicate transient capacity issues
_TRANSIENT_HTTP_CODES = {429, 503, 529}
_TRANSIENT_GRPC_STATUSES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE"}


def _is_transient(exc: Exception) -> bool:
    """Return True only for capacity/rate-limit errors that warrant model fallback."""
    if isinstance(exc, (ClientError, ServerError)):
        if exc.code in _TRANSIENT_HTTP_CODES:
            return True
        msg = str(exc).upper()
        return any(s in msg for s in _TRANSIENT_GRPC_STATUSES)
    return False


def _get_google_genai_version() -> str:
    """Return the installed google-genai package version."""
    try:
        return importlib.metadata.version("google-genai")
    except Exception:
        return getattr(genai, "__version__", "unknown")


def _safe_lines_preview(text: str, start_line: int = 15, end_line: int = 24) -> str:
    """Extract a safe preview of text between line numbers (1-indexed) without exposing full text."""
    lines = text.splitlines()
    if not lines:
        return ""
    start_idx = max(0, start_line - 1)
    end_idx = min(len(lines), end_line)
    return "\n".join(lines[start_idx:end_idx])


def _extract_json_str(content: str) -> str:
    """Extract clean JSON string from potentially markdown-fenced or noisy LLM output."""
    trimmed = content.strip()
    match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?```", trimmed, re.IGNORECASE)
    if match:
        trimmed = match.group(1).strip()

    if not (trimmed.startswith("{") or trimmed.startswith("[")):
        first_brace = trimmed.find("{")
        last_brace = trimmed.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            trimmed = trimmed[first_brace:last_brace + 1]
    return trimmed


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None, models: Optional[list[str]] = None):
        from backend.config import settings
        api_key_val = api_key or settings.gemini_api_key or "dummy-key-for-testing"
        self.client = genai.Client(api_key=api_key_val)
        if models is not None:
            self._models = models
        else:
            primary = settings.gemini_primary_model
            fallbacks_raw = settings.gemini_fallback_models
            fallbacks = [m.strip() for m in fallbacks_raw.split(",") if m.strip()] if fallbacks_raw else []
            self._models = [primary] + fallbacks

    # ------------------------------------------------------------------ #
    # Internal single-model call (no fallback logic here)
    # ------------------------------------------------------------------ #
    async def _generate_once(
        self,
        messages: list[LLMMessage],
        model: str,
        temperature: float,
        max_tokens: Optional[int],
        response_format: Optional[type[BaseModel]],
    ) -> LLMResponse:
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            elif m.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part(text=m.content)]))
            elif m.role == "assistant":
                contents.append(types.Content(role="model", parts=[types.Part(text=m.content)]))

        config_kwargs: dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            config_kwargs["max_output_tokens"] = max_tokens
        if response_format:
            config_kwargs["response_mime_type"] = "application/json"
            config_kwargs["response_schema"] = response_format
        if system_parts:
            config_kwargs["system_instruction"] = "\n\n".join(system_parts)

        gen_config = types.GenerateContentConfig(**config_kwargs)

        response = await self.client.aio.models.generate_content(
            model=model,
            contents=contents,
            config=gen_config,
        )

        if not response.candidates:
            raise ValueError("API returned no candidates")

        candidate = response.candidates[0]
        if not candidate.content or not candidate.content.parts:
            raise ValueError("API returned empty content")

        content = candidate.content.parts[0].text
        if content is None:
            raise ValueError("API returned None text content")

        tokens_used = 0
        if response.usage_metadata:
            tokens_used = response.usage_metadata.total_token_count or 0

        metadata = {
            "finish_reason": str(candidate.finish_reason) if candidate.finish_reason else None,
            "parsed": getattr(response, "parsed", None),
            "response_schema_present": bool(response_format),
            "response_mime_type": config_kwargs.get("response_mime_type"),
        }

        return LLMResponse(
            content=content,
            model=model,
            tokens_used=tokens_used,
            metadata=metadata,
        )

    # ------------------------------------------------------------------ #
    # Public generate() with fallback chain
    # ------------------------------------------------------------------ #
    async def generate(
        self,
        messages: list[LLMMessage],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[type[BaseModel]] = None,
    ) -> LLMResponse:
        # Build ordered model list: explicit model first, then configured chain
        if model and model not in self._models:
            candidates = [model] + self._models
        elif model:
            # Rotate so the requested model is tried first
            idx = self._models.index(model)
            candidates = self._models[idx:]
        else:
            candidates = self._models

        last_exc: Exception = RuntimeError("No models configured")
        for i, m in enumerate(candidates):
            logger.info("llm_generate_start", model=m, message_count=len(messages))
            try:
                result = await self._generate_once(messages, m, temperature, max_tokens, response_format)
                logger.info("llm_generate_complete", model=m, tokens_used=result.tokens_used)
                return result
            except Exception as exc:
                last_exc = exc
                if _is_transient(exc) and i < len(candidates) - 1:
                    next_model = candidates[i + 1]
                    logger.warning(
                        "llm_model_fallback",
                        failed_model=m,
                        next_model=next_model,
                        reason=str(exc)[:120],
                    )
                    continue
                # Non-transient or no fallback left
                logger.error("llm_generate_error", error=str(exc), model=m, error_type=type(exc).__name__)
                raise

        raise last_exc

    # ------------------------------------------------------------------ #
    # Public generate_structured() — delegates to generate()
    # ------------------------------------------------------------------ #
    async def generate_structured(
        self,
        messages: list[LLMMessage],
        model: str,
        response_schema: type[BaseModel],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 2048,
    ) -> BaseModel:
        logger.info("llm_generate_structured_start", model=model, schema=response_schema.__name__)

        schema_instruction = (
            f"\nYou must respond with valid JSON matching this schema: "
            f"{response_schema.model_json_schema()}"
        )

        base_messages = list(messages)
        if base_messages and base_messages[0].role == "system":
            base_messages[0] = LLMMessage(
                role="system",
                content=base_messages[0].content + schema_instruction,
            )
        else:
            base_messages.insert(0, LLMMessage(role="system", content=schema_instruction))

        max_attempts = 2
        last_exc: Optional[Exception] = None
        raw_response_content = ""

        for attempt in range(1, max_attempts + 1):
            attempt_messages = list(base_messages)
            if attempt > 1 and last_exc:
                retry_prompt = (
                    f"Previous attempt produced invalid structured output: {last_exc}. "
                    f"Please output strictly valid JSON conforming exactly to the {response_schema.__name__} schema."
                )
                attempt_messages.append(LLMMessage(role="user", content=retry_prompt))

            response: Optional[LLMResponse] = None
            try:
                response = await self.generate(
                    attempt_messages,
                    model=model,
                    temperature=temperature,
                    response_format=response_schema,
                    max_tokens=max_tokens,
                )
                raw_response_content = response.content or ""

                # 1. Prefer SDK's native parsed response when available and valid
                sdk_parsed = response.metadata.get("parsed") if response.metadata else None
                if sdk_parsed is not None:
                    if isinstance(sdk_parsed, response_schema):
                        if attempt > 1:
                            logger.info(
                                "llm_generate_structured_retry_success",
                                attempt=attempt,
                                schema=response_schema.__name__,
                                parsed_source="sdk_native",
                            )
                        else:
                            logger.info(
                                "llm_generate_structured_complete",
                                schema=response_schema.__name__,
                                parsed_source="sdk_native",
                            )
                        return sdk_parsed
                    elif isinstance(sdk_parsed, dict):
                        try:
                            result = response_schema.model_validate(sdk_parsed)
                            if attempt > 1:
                                logger.info(
                                    "llm_generate_structured_retry_success",
                                    attempt=attempt,
                                    schema=response_schema.__name__,
                                    parsed_source="sdk_dict_validated",
                                )
                            else:
                                logger.info(
                                    "llm_generate_structured_complete",
                                    schema=response_schema.__name__,
                                    parsed_source="sdk_dict_validated",
                                )
                            return result
                        except ValidationError as val_err:
                            logger.warning(
                                "llm_generate_structured_sdk_parsed_validation_error",
                                attempt=attempt,
                                error=str(val_err),
                                schema=response_schema.__name__,
                            )

                # 2. Fall back to response text and validate using model_validate_json()
                try:
                    result = response_schema.model_validate_json(raw_response_content)
                except (ValidationError, ValueError) as direct_err:
                    # Narrowly scoped fallback for harmless markdown fences / preambles
                    clean_text = _extract_json_str(raw_response_content)
                    try:
                        result = response_schema.model_validate_json(clean_text)
                    except (ValidationError, ValueError) as clean_err:
                        raise clean_err from direct_err

                if attempt > 1:
                    logger.info(
                        "llm_generate_structured_retry_success",
                        attempt=attempt,
                        schema=response_schema.__name__,
                        parsed_source="text_fallback",
                    )
                else:
                    logger.info(
                        "llm_generate_structured_complete",
                        schema=response_schema.__name__,
                        parsed_source="text_fallback",
                    )
                return result

            except Exception as e:
                last_exc = e
                # Diagnostic logging for failing request
                logger.warning(
                    "llm_generate_structured_diagnostic_failure",
                    sdk_version=_get_google_genai_version(),
                    model=model,
                    schema=response_schema.__name__,
                    response_schema_present=response.metadata.get("response_schema_present", False) if response and response.metadata else False,
                    response_mime_type=response.metadata.get("response_mime_type", "") if response and response.metadata else "",
                    response_parsed_populated=response.metadata.get("parsed") is not None if response and response.metadata else False,
                    response_text_length=len(raw_response_content),
                    preview_lines_15_24=_safe_lines_preview(raw_response_content, 15, 24),
                    finish_reason=response.metadata.get("finish_reason", "UNKNOWN") if response and response.metadata else "UNKNOWN",
                    attempt=attempt,
                    error=str(e),
                    error_type=type(e).__name__,
                )

                if attempt < max_attempts:
                    logger.warning(
                        "llm_generate_structured_retry",
                        attempt=attempt,
                        next_attempt=attempt + 1,
                        schema=response_schema.__name__,
                        error=str(e),
                        error_type=type(e).__name__,
                    )
                    continue
                else:
                    logger.error(
                        "llm_generate_structured_error",
                        attempts=max_attempts,
                        error=str(e),
                        schema=response_schema.__name__,
                        error_type=type(e).__name__,
                    )
                    raise
