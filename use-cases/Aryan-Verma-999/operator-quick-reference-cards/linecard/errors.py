"""Stable, secret-free normalization of provider and transport failures."""
from __future__ import annotations
import json
from typing import Any

def normalize_error(exc: Any = None, *, status: int | None = None, body: Any = None, headers: dict[str,str] | None = None) -> dict[str, Any]:
    headers = {str(k).lower(): str(v) for k,v in (headers or {}).items()}
    if status in {401,403}: category, retryable, recovery = "AUTHENTICATION" if status == 401 else "AUTHORIZATION", False, "check credentials and document ownership"
    elif status == 400: category, retryable, recovery = "BAD_REQUEST", False, "inspect request fields"
    elif status == 404: category, retryable, recovery = "NOT_FOUND", False, "refresh the document or job"
    elif status == 409: category, retryable, recovery = "CONFLICT", False, "reconcile the current revision before retrying"
    elif status in {413,415,422}: category, retryable, recovery = "VALIDATION", False, "correct the upload or request"
    elif status == 429: category, retryable, recovery = "RATE_LIMIT", True, "wait for the retry window"
    elif status in {500,504}: category, retryable, recovery = "UPSTREAM_FAILURE", True, "reconcile state, then retry once"
    elif isinstance(exc, TimeoutError) or (exc and type(exc).__name__.lower().endswith("timeout")): category, retryable, recovery = "TIMEOUT", True, "reconcile before retrying"
    elif exc and "dns" in str(exc).lower(): category, retryable, recovery = "DNS_FAILURE", True, "restore DNS/network access"
    elif exc: category, retryable, recovery = "CONNECTION_FAILURE", True, "check network access and reconcile"
    else: category, retryable, recovery = "UNKNOWN", False, "contact the operator"
    retry_after = headers.get("retry-after") if status == 429 else None
    return {"category": category, "status": status, "cause": str(exc or body or "provider error")[:240], "retryable": retryable,
            "retry_after": retry_after, "suggested_recovery": recovery,
            "message": "LineCard could not complete this operation safely; review the error and reconcile state."}

def parse_response(status: int, body: bytes, headers: dict[str,str] | None = None) -> dict[str, Any]:
    try: payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError): payload = {"raw": "non-json response"}
    return normalize_error(status=status, body=payload, headers=headers)
