"""Settings from environment. Keep the SuperDocs key server-side only."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    superdocs_api_key: str = os.environ.get("SUPERDOCS_API_KEY", "")
    export_format: str = os.environ.get("EXPORT_FORMAT", "docx")
    # Base HTML a fresh "draft" starts from (SuperDocs edits an existing doc under HITL).
    seed_template: str = os.environ.get(
        "SEED_TEMPLATE",
        "<h1>Draft</h1><p>Replace this with the requested content.</p>",
    )
    # Google Chat webhook auth. Unset => auth disabled (local/dev). Set it to the
    # audience configured on the Chat app connection (project number or app URL).
    chat_audience: str = os.environ.get("GOOGLE_CHAT_AUDIENCE", "")
    # Shared secret a scheduler presents to the daily-digest endpoint.
    digest_token: str = os.environ.get("DIGEST_TOKEN", "")


settings = Settings()
