"""Meeting UUIDs from Zoom's own SDK are base64-shaped and routinely contain
/, +, = (confirmed live — see PROGRESS.md M3). A raw / inside a path segment
breaks routing even when percent-encoded: confirmed directly against this
app's own routes that a properly-escaped %2F still 404s, because Starlette's
default path-parameter matching doesn't accept encoded slashes outside a
:path-typed, route-terminal segment — and meeting_uuid here sits in the
middle of the path (.../{meeting_uuid}/state), not at the end.

The frontend base64url-encodes the meeting UUID before building any URL
(base64url's alphabet never contains /, so this side-steps the problem
entirely rather than fighting the framework); every route here decodes it
back to the real value before use.
"""

from __future__ import annotations

import base64


def decode_meeting_uuid(encoded: str) -> str:
    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        return base64.urlsafe_b64decode(padded).decode()
    except (ValueError, base64.binascii.Error):
        raise ValueError("invalid meeting uuid")
