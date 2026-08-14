"""API key generation and hashing.

We generate a high-entropy random key, show it to the caller exactly once, and
store only its SHA-256 hash. Lookups hash the presented key and compare, so the
plaintext never touches the database or logs.

SHA-256 (not bcrypt) is deliberate: API keys are already 256 bits of entropy, so
they are not brute-forceable the way human passwords are, and we want O(1)
constant-time-ish lookups by hash on every request.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

KEY_PREFIX = "tdg_"  # tenant-doc-gateway, so keys are recognizable in the wild.


def generate_api_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def key_prefix(plaintext: str) -> str:
    # Stored to help operators identify a key without revealing it.
    return plaintext[:12]


def verify_admin_key(presented: str, expected: str) -> bool:
    # Constant-time compare to avoid timing side-channels on the admin secret.
    return hmac.compare_digest(presented, expected)
