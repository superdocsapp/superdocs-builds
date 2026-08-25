"""Cerebras Inference provider using the OpenAI-compatible API."""
import json
from typing import Any, Optional

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from backend.core.llm.provider import LLMProvider, LLMMessage, LLMResponse
from backend.logging_config import get_logger

logger = get_logger(__name__)

CEREBRAS_BASE_URL = "https://api.cerebras.ai/v1"


class CerebrasProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        from backend.config import settings
        self.client = AsyncOpenAI(
            api_key=api_key or settings.cerebras_api_key,
            base_url=CEREBRAS_BASE_URL,
        )

    async def generate(
        self,
        messages: list[LLMMessage],
        model: str = "gpt-oss-120b",
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        response_format: Optional[type[BaseModel]] = None,
    ) -> LLMResponse:
        logger.info("llm_generate_start", model=model, message_count=len(messages))

        messages_dict = [{"role": m.role, "content": m.content} for m in messages]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages_dict,
            "temperature": temperature,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        if response_format:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            completion = await self.client.chat.completions.create(**kwargs)

            if not completion.choices or len(completion.choices) == 0:
                logger.error("llm_generate_error", error="No choices in response", model=model)
                raise ValueError("API returned no completion choices")

            if not completion.choices[0].message:
                raise ValueError("API returned no message in choice")

            content = completion.choices[0].message.content
            if content is None:
                raise ValueError("API returned None content")

            tokens_used = completion.usage.total_tokens if completion.usage else 0
            logger.info("llm_generate_complete", model=model, tokens_used=tokens_used)

            return LLMResponse(
                content=content,
                model=model,
                tokens_used=tokens_used,
                metadata={"finish_reason": completion.choices[0].finish_reason},
            )
        except Exception as e:
            logger.error("llm_generate_error", error=str(e), model=model, error_type=type(e).__name__)
            raise

    async def generate_structured(
        self,
        messages: list[LLMMessage],
        model: str,
        response_schema: type[BaseModel],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 2048,
    ) -> BaseModel:
        logger.info("llm_generate_structured_start", model=model, schema=response_schema.__name__)

        try:
            schema_instruction = (
                f"\nYou must respond with valid JSON matching this schema: "
                f"{response_schema.model_json_schema()}"
            )

            modified_messages = messages.copy()
            if modified_messages and modified_messages[0].role == "system":
                modified_messages[0] = LLMMessage(
                    role="system",
                    content=modified_messages[0].content + schema_instruction,
                )
            else:
                modified_messages.insert(0, LLMMessage(role="system", content=schema_instruction))

            response = await self.generate(
                modified_messages,
                model=model,
                temperature=temperature,
                response_format=response_schema,
                max_tokens=max_tokens,
            )

            try:
                parsed = json.loads(response.content)
            except json.JSONDecodeError as e:
                logger.error("llm_generate_structured_json_error", error=str(e), content=response.content[:100])
                raise ValueError(f"Failed to parse JSON response: {e}")

            try:
                result = response_schema(**parsed)
            except ValidationError as e:
                logger.error("llm_generate_structured_validation_error", error=str(e), schema=response_schema.__name__)
                raise ValueError(f"Response does not match schema {response_schema.__name__}: {e}")

            logger.info("llm_generate_structured_complete", schema=response_schema.__name__)
            return result

        except Exception as e:
            logger.error("llm_generate_structured_error", error=str(e), schema=response_schema.__name__, error_type=type(e).__name__)
            raise
