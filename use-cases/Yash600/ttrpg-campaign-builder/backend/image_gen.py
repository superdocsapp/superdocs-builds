"""
image_gen.py -- illustration generation, kept deliberately separate from
SuperDocs' own concerns.

Generation itself (image.pollinations.ai) is free, keyless, and NOT part of
SuperDocs -- it's a plain GET that returns image bytes. This module's only
job is turning a text prompt into bytes. What happens to those bytes
(uploading them through SuperDocs' own image endpoint to get an embeddable
URL, then writing an <img> tag into a document via chat) is main.py's job,
because that part IS the SuperDocs "images" surface and belongs with the
other SuperDocs-calling code.

Swappable by design: if you'd rather use a paid provider (DALL-E, Stability,
etc.), this is the one function to replace -- everything downstream just
wants (bytes, content_type).
"""

from __future__ import annotations

from urllib.parse import quote

import requests

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


class ImageGenError(RuntimeError):
    pass


def generate_illustration(
    prompt: str,
    *,
    width: int = 1024,
    height: int = 1024,
    seed: int | None = None,
    timeout: int = 90,
) -> tuple[bytes, str]:
    """
    GET https://image.pollinations.ai/prompt/<url-encoded prompt>?width=&height=&nologo=true

    Returns (image_bytes, content_type). Keyless -- no account, no API key,
    no cost. Deliberately synchronous: this project's FastAPI routes are
    plain `def` (see main.py), which FastAPI already runs in a worker
    thread, so a blocking network call here doesn't block the event loop.
    """
    url = f"{POLLINATIONS_BASE}/{quote(prompt)}"
    params = {"width": width, "height": height, "nologo": "true"}
    if seed is not None:
        params["seed"] = seed

    try:
        resp = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as e:
        raise ImageGenError(f"image generation request failed: {e}") from e

    if resp.status_code >= 400:
        raise ImageGenError(f"image generation returned {resp.status_code}: {resp.text[:200]}")

    content_type = resp.headers.get("Content-Type", "image/jpeg")
    if not content_type.startswith("image/"):
        raise ImageGenError(f"image generation did not return an image (got {content_type})")

    return resp.content, content_type
