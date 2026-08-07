"""Key loading and, more importantly, key REDACTION.

Rule enforced here: an API key never reaches a log line, a recorded
fixture, a committed file, or an exception message. There is exactly one
function that can print a request, and it runs everything through
``redact()`` first.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

# SuperDocs keys look like sk_<32 hex>. The second alternative catches
# anything else long enough to be a credential sitting in an auth header.
_KEY_RE = re.compile(r"\b(sk_[A-Za-z0-9]{8,})\b")
_BEARER_RE = re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]{12,})")


def redact(value):
    """Recursively replace anything that looks like a credential.

    Works on str/dict/list so it can be applied to a whole request body
    before it is written anywhere.
    """
    if isinstance(value, str):
        out = _KEY_RE.sub("sk_REDACTED", value)
        return _BEARER_RE.sub(r"\1REDACTED", out)
    if isinstance(value, dict):
        return {
            k: ("REDACTED" if k.lower() in _SECRET_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


_SECRET_KEYS = {"authorization", "api_key", "apikey", "x-api-key", "token", "secret"}


def load_env(start: Path | None = None) -> None:
    """Load KEY=VALUE lines from the nearest ancestor .env. Never overwrites
    a variable already set in the real environment (CI wins over a local file).
    """
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            for raw in candidate.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                os.environ.setdefault(key.strip(), val.strip().strip("'\""))
            return


def api_key(required: bool = True) -> str:
    load_env()
    key = os.environ.get("SUPERDOCS_API_KEY", "").strip()
    if required and (not key or key == "your-key-here"):
        from .errors import AuthError

        raise AuthError(
            "SUPERDOCS_API_KEY is not set.",
            "cp .env.example .env and paste a key, or run the agent self-signup "
            "in .env.example. Tests do not need a key: `make test` replays fixtures.",
        )
    return key


def base_url() -> str:
    load_env()
    return os.environ.get("SUPERDOCS_BASE_URL", "https://api.superdocs.app").rstrip("/")
