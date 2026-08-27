import json

import httpx

from app.config import get_settings

SYSTEM_PROMPT = (
    "You are a strict data extraction engine. You extract structured field values "
    "from unstructured HR text. Respond with ONLY a single JSON object - no prose, "
    "no markdown fences, no explanations.\n\n"
    "Rules:\n"
    "- Never invent information that is not present in the input.\n"
    "- If a field's value is not clearly present in the input, set it to null.\n"
    "- Only return the fields listed in the schema below. Do not add extra keys.\n"
    "- Return the raw values you find as plain text or numbers; the caller will "
    "handle final date, salary, and boolean normalization.\n"
    "- Do not generate document content or prose.\n"
    "- Do not change, reference, or reason about any document template."
)


class AIExtractionError(Exception):
    pass


def _build_user_prompt(field_schema: dict, text: str) -> str:
    schema_lines = []
    for field_key, field_def in field_schema.items():
        field_type = field_def.get("type", "string") if isinstance(field_def, dict) else "string"
        required = bool(field_def.get("required")) if isinstance(field_def, dict) else False
        schema_lines.append(f'- "{field_key}": type={field_type}, required={required}')

    return (
        "Template schema fields:\n"
        + "\n".join(schema_lines)
        + "\n\nUser input:\n"
        + text
        + "\n\nRespond with a single JSON object whose keys are exactly the field "
        "names above and whose values are the extracted raw values (or null)."
    )


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.lower().startswith("json"):
            content = content[4:]
        content = content.strip()
    return content


async def extract_fields_with_ai(field_schema: dict, text: str) -> dict:
    """Call OpenRouter to extract schema fields from unstructured text.

    Only used for natural language / email / bullet-point input - JSON and
    CSV input are parsed deterministically and never sent to the AI. The AI
    response is filtered down to exactly the fields declared in the schema;
    anything else it returns is discarded.
    """
    settings = get_settings()
    if not settings.openrouter_api_key:
        raise AIExtractionError(
            "OpenRouter is not configured. Set OPENROUTER_API_KEY in the backend .env file."
        )

    payload = {
        "model": settings.openrouter_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(field_schema, text)},
        ],
        "temperature": 0,
    }

    headers = {
        "Authorization": f"Bearer {settings.openrouter_api_key}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=settings.openrouter_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise AIExtractionError("OpenRouter request timed out.") from exc
    except httpx.HTTPError as exc:
        raise AIExtractionError(f"Could not reach OpenRouter: {exc}") from exc

    if response.status_code != 200:
        raise AIExtractionError(
            f"OpenRouter returned an error (status {response.status_code}): {response.text[:500]}"
        )

    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, ValueError) as exc:
        raise AIExtractionError("OpenRouter returned an unexpected response shape.") from exc

    content = _strip_code_fence(content)

    try:
        extracted = json.loads(content)
    except json.JSONDecodeError as exc:
        raise AIExtractionError(f"AI response was not valid JSON: {exc.msg}") from exc

    if not isinstance(extracted, dict):
        raise AIExtractionError("AI response must be a JSON object.")

    allowed_keys = set(field_schema.keys())
    return {key: value for key, value in extracted.items() if key in allowed_keys}
