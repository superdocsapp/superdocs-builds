"""DeepSeek LLM client using the OpenAI-compatible API.

Provides a unified interface for all pipeline nodes that need LLM capabilities:
classification, claim extraction, rule matching, and confidence scoring.

Configuration via environment variables:
    DEEPSEEK_API_KEY - API key for DeepSeek
    DEEPSEEK_MODEL - Model to use (default: deepseek-chat)
    DEEPSEEK_BASE_URL - Base URL (default: https://api.deepseek.com)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def get_deepseek_client() -> AsyncOpenAI:
    """Get or create the DeepSeek async client."""
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        if not api_key:
            raise RuntimeError(
                "DEEPSEEK_API_KEY environment variable is required. "
                "Set it in .env or export it."
            )
        _client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    return _client


def get_model() -> str:
    """Get the configured model name."""
    return os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


async def chat_completion(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
    response_format: Optional[dict] = None,
) -> tuple[str, int, int]:
    """Make a chat completion request to DeepSeek.

    Args:
        system_prompt: System message content.
        user_prompt: User message content.
        temperature: Sampling temperature (low for deterministic output).
        max_tokens: Maximum tokens in response.
        response_format: Optional response format spec (e.g., {"type": "json_object"}).

    Returns:
        Tuple of (response_text, input_tokens, output_tokens).
    """
    client = get_deepseek_client()
    model = get_model()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)

    content = response.choices[0].message.content or ""
    usage = response.usage
    input_tokens = usage.prompt_tokens if usage else 0
    output_tokens = usage.completion_tokens if usage else 0

    return content, input_tokens, output_tokens


async def chat_completion_json(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> tuple[Any, int, int]:
    """Make a chat completion request expecting JSON response.

    Returns parsed JSON plus token counts.
    """
    content, inp, out = await chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code blocks
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.index("```", start)
            parsed = json.loads(content[start:end].strip())
        elif "```" in content:
            start = content.index("```") + 3
            end = content.index("```", start)
            parsed = json.loads(content[start:end].strip())
        else:
            logger.error("Failed to parse JSON from LLM response: %s", content[:200])
            parsed = {}

    return parsed, inp, out
