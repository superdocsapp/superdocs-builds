"""Redaction applied to every recorded interaction, on write.

This is defence in depth, not the primary control. The primary control is that only
fabricated content is ever sent to the live service in the first place (see corpus/).
A scrubber you rely on is a scrubber that will one day miss something; a scrubber
guarding input that was never sensitive is cheap insurance.

Everything here is deterministic: the same input always redacts to the same output, so
scrubbing never introduces flake into a replayed fixture.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Header names are compared lower-cased.
DROP_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "cookie",
        "set-cookie",
        "x-api-key",
        "api-key",
    }
)

# Response headers worth keeping. Everything else is noise that would make cassettes
# churn between recordings (dates, request ids, CDN internals) without adding fidelity.
KEEP_RESPONSE_HEADERS = frozenset(
    {
        "content-type",
        "content-disposition",
        "retry-after",
        "x-usage-limit",
        "x-usage-used",
        "x-usage-remaining",
        "x-export-warnings",
        "mcp-session-id",
        "mcp-protocol-version",
        "cache-control",
    }
)

PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # API keys, personal and organization.
    (re.compile(r"\bsk_[A-Za-z0-9]{8,}"), "sk_REDACTED"),
    (re.compile(r"\blce_[A-Za-z0-9]{8,}"), "lce_REDACTED"),
    # Bearer tokens wherever they appear in a body or a URL.
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer " + REDACTED),
    (re.compile(r"(?i)([?&]api_key=)[^&\s\"']+"), r"\1" + REDACTED),
    # Pre-signed storage URLs carry credentials in their query string. Keep the shape,
    # drop the signature: an integrator still sees "a URL came back", which is the
    # only thing a mock needs to reproduce.
    (
        re.compile(r"(?i)([?&](?:X-Amz-Signature|X-Amz-Credential|X-Amz-Security-Token|"
                   r"Signature|AWSAccessKeyId|se|sig|st|sp|sv)=)[^&\s\"']+"),
        r"\1" + REDACTED,
    ),
]

# Account identifiers nested inside a JSON-encoded *string* -- MCP tool results carry
# their payload as text, and the double-encoded proposed_change_batch content does the
# same. Key-based redaction walks decoded structures and cannot see into those, so this
# catches them textually.
#
# Matched and replaced in place rather than by re-serialising the embedded JSON: the
# double-encoded payload's exact bytes are part of what the mock has to reproduce, and
# re-encoding it would quietly reformat a fixture that integrators parse.
_NESTED_IDENTIFIER = re.compile(
    r'("(?:account_id|user_id|organization_id|owner_id|redemption_id|support_event_id)"'
    r'\s*:\s*")(?!\[REDACTED\])[^"]{6,}(")'
)

# Addresses that are public constants rather than anyone's personal data. SuperDocs
# publishes this one in its own error bodies and docs, and an integrator handling a
# capacity refusal needs to see it -- redacting it would make the fixture less useful
# and no safer.
PUBLIC_ADDRESSES = frozenset({"hello@superdocs.app", "user@example.com",
                              "redacted@example.com"})

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")


def _redact_email(match: re.Match[str]) -> str:
    address = match.group(0)
    return address if address.lower() in PUBLIC_ADDRESSES else "redacted@example.com"

# Keys whose values are always replaced regardless of shape, because they identify the
# account rather than describing behaviour.
SENSITIVE_KEYS = frozenset(
    {
        "account_id",
        "user_id",
        "organization_id",
        "owner_id",
        "recipient_email",
        "email",
        # NB: `contact_email` is deliberately absent -- it carries SuperDocs' own public
        # support address, which the capacity refusal tells integrators to write to.
        "support_event_id",
        "redemption_id",
        "api_key",
        "key",
        "token",
        "access_token",
    }
)

# Exceptions: these are structural, not identifying, and replay needs them intact.
KEEP_KEYS = frozenset({"session_id", "job_id", "change_id", "chunk_id", "document_id",
                       "version_id", "upload_id", "attachment_id", "template_id"})


def scrub_text(value: str) -> str:
    for pattern, replacement in PATTERNS:
        value = pattern.sub(replacement, value)
    value = _NESTED_IDENTIFIER.sub(r"\1" + REDACTED + r"\2", value)
    return _EMAIL.sub(_redact_email, value)


def scrub_value(value: Any, key: str | None = None) -> Any:
    """Recursively redact a decoded JSON structure."""
    if key is not None and key.lower() in SENSITIVE_KEYS and key.lower() not in KEEP_KEYS:
        if value is None:
            return None
        return REDACTED if not isinstance(value, (int, float, bool)) else value
    if isinstance(value, dict):
        return {k: scrub_value(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_value(v) for v in value]
    if isinstance(value, str):
        return scrub_text(value)
    return value


def scrub_headers(headers: dict[str, str], *, keep: frozenset[str] | None = None) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, value in headers.items():
        lower = name.lower()
        if lower in DROP_HEADERS:
            continue
        if keep is not None and lower not in keep:
            continue
        out[lower] = scrub_text(value)
    return dict(sorted(out.items()))


def audit(blob: str) -> list[str]:
    """Return the reasons a serialized cassette would fail the secrecy gate.

    Used by the CI test over every committed cassette. Deliberately independent of the
    scrubber's own patterns where it can be: a scrubber and its test that share all
    their logic only prove the logic is self-consistent.
    """
    problems: list[str] = []
    # Check the escaped form too. A cassette stores MCP tool results and the
    # double-encoded proposed_change_batch payload as JSON *inside* JSON, so on disk the
    # inner quotes are backslash-escaped and a naive pattern walks straight past them --
    # which is exactly how a real account_id got through the first version of this check.
    blob = blob + "\n" + blob.replace('\\"', '"')

    if re.search(r"\bsk_(?!REDACTED)[A-Za-z0-9]{8,}", blob):
        problems.append("a personal API key (sk_) survives in the payload")
    if re.search(r"\blce_(?!REDACTED)[A-Za-z0-9]{8,}", blob):
        problems.append("an organization API key (lce_) survives in the payload")
    for match in re.finditer(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", blob):
        address = match.group(0)
        if address in {"redacted@example.com", "hello@superdocs.app", "user@example.com"}:
            continue
        problems.append(f"an email address survives in the payload: {address}")
    if re.search(r"(?i)X-Amz-Signature=(?!\[REDACTED\])", blob):
        problems.append("a pre-signed URL signature survives in the payload")
    if re.search(r"(?i)\bBearer\s+(?!\[REDACTED\])[A-Za-z0-9._\-]{8,}", blob):
        problems.append("a bearer token survives in the payload")
    # Account identifiers, including ones nested inside a JSON-encoded string. This
    # check exists because the earlier version did not have it and a real account_id
    # reached a committed cassette through an MCP tool result, where the payload is
    # carried as text and key-based redaction never looked.
    for match in re.finditer(
        r'"(account_id|user_id|organization_id|owner_id|redemption_id|'
        r'support_event_id)"\s*:\s*"([^"]+)"',
        blob,
    ):
        if match.group(2) != REDACTED:
            problems.append(
                f"an account identifier survives in the payload: {match.group(1)}"
            )
    return problems
