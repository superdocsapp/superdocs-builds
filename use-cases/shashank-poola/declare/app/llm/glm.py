from __future__ import annotations

import json
import re
from typing import Any

import httpx
from config.env import get_settings


class GLMError(Exception):
    pass


def _unfence(content: str) -> str:
    content = content.strip()
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else content


async def analyze_with_glm(messages: list[dict[str, str]]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.glm_api_key:
        raise GLMError("GLM_PROVIDER_NOT_CONFIGURED")
    payload = {
        "model": settings.glm_model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "enabled"},
        "reasoning_effort": "low",
        "stream": False,
    }
    try:
        timeout = httpx.Timeout(settings.glm_timeout_ms / 1000)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.glm_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {settings.glm_api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            provider = response.json()
        content = provider["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise GLMError("DECLARE_ANALYSIS_FAILED")
        return json.loads(_unfence(content))
    except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GLMError("DECLARE_ANALYSIS_FAILED") from error
