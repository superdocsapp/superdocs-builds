"""Shared Gemini call path. One place for the model, SSL context, and request
shape, used by both the corpus prose stage and the live H3 checker so they
cannot drift into two different notions of "how we call Gemini"."""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request

MODEL = "gemini-3.5-flash-lite"
ENDPOINT = ("https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent")


def ssl_context():
    """Verified TLS. certifi supplies the root store the venv lacks on macOS."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def call_gemini(prompt: str, api_key: str, *, model: str = MODEL,
                temperature: float = 0, timeout: int = 60) -> str:
    payload = json.dumps({
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature, "topP": 1},
    }).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT.format(model=model), data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key})
    with urllib.request.urlopen(req, timeout=timeout,
                                context=ssl_context()) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["candidates"][0]["content"]["parts"][0]["text"].strip()
