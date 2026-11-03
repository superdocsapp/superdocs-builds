"""Thin wrapper around the Box API surface this workflow needs.

Kept deliberately narrow: file download, metadata template read/update,
governance-state read, and webhook signature verification. Nothing here
does spreadsheet editing or live multiplayer anything -- out of scope by
the task brief, not by omission.

This client is written against Box's real REST shape (see
https://developer.box.com/reference/) so swapping the transport for a
live Box SDK is a drop-in change; for this task it is exercised entirely
through FakeBoxClient in tests, since no live Box tenant is available.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models import BoxFileVersion, GovernanceState


class BoxAPIError(Exception):
    pass


class BoxClient(ABC):
    """Interface. A real implementation talks to api.box.com; tests use FakeBoxClient."""

    @abstractmethod
    def get_file_version(self, file_id: str) -> BoxFileVersion: ...

    @abstractmethod
    def download_file(self, file_id: str) -> bytes: ...

    @abstractmethod
    def get_governance_state(self, file_id: str) -> GovernanceState: ...

    @abstractmethod
    def get_metadata(self, file_id: str, template_key: str) -> dict[str, Any]: ...

    @abstractmethod
    def update_metadata(
        self, file_id: str, template_key: str, fields: dict[str, Any]
    ) -> dict[str, Any]:
        """Apply a JSON-Patch-style partial update. Must only touch the keys given."""
        ...

    @abstractmethod
    def upload_companion_document(
        self, parent_folder_id: str, filename: str, content: bytes
    ) -> str:
        """Returns the new file's Box file ID."""
        ...


def verify_box_webhook_signature(
    body: bytes, headers: dict[str, str], primary_key: str, secondary_key: Optional[str] = None
) -> bool:
    """Mirrors Box's HMAC-SHA256 webhook signature scheme.

    Box sends BOX-SIGNATURE-PRIMARY / BOX-SIGNATURE-SECONDARY plus a
    delivery timestamp and version headers. We recompute HMAC-SHA256 over
    (body + timestamp) with each configured key and accept if either
    matches -- this is what lets a key be rotated without downtime, which
    is why Box supports two keys in the first place.
    """
    timestamp = headers.get("BOX-DELIVERY-TIMESTAMP", "")
    if not timestamp:
        return False

    # Reject stale deliveries (Box recommends a 10 minute window) to close
    # a replay-attack path a pure signature check would leave open.
    try:
        delivered_at = float(timestamp)
    except ValueError:
        # Box actually sends an ISO8601 timestamp; support both shapes.
        import datetime

        try:
            delivered_at = datetime.datetime.fromisoformat(
                timestamp.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return False
    if abs(time.time() - delivered_at) > 600:
        return False

    signed_payload = body + timestamp.encode()
    candidates = [k for k in (primary_key, secondary_key) if k]
    provided = [
        headers.get("BOX-SIGNATURE-PRIMARY", ""),
        headers.get("BOX-SIGNATURE-SECONDARY", ""),
    ]
    for key in candidates:
        expected = hmac.new(key.encode(), signed_payload, hashlib.sha256).hexdigest()
        for sig in provided:
            if sig and hmac.compare_digest(expected, sig):
                return True
    return False
