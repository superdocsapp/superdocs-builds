"""Secret redaction — apply before logging anything that might carry
`Authorization` or other sensitive headers/values (e.g. `_JSONRPC_HEADERS`
merged with the per-request `Authorization: Bearer ...` in
`superdocs_client._call_tool`). No logging infrastructure exists in this
codebase yet; this is ready to wire in the moment one is added, per
docs/SECURITY.md.
"""

from __future__ import annotations

_REDACTED = "***REDACTED***"
_SENSITIVE_HEADER_NAMES = {"authorization", "x-api-key", "api-key", "cookie", "set-cookie"}


def redact_headers(headers: dict) -> dict:
    """Return a copy of `headers` with sensitive header values masked,
    case-insensitively. Non-sensitive headers pass through unchanged."""

    return {
        key: (_REDACTED if key.lower() in _SENSITIVE_HEADER_NAMES else value)
        for key, value in headers.items()
    }
