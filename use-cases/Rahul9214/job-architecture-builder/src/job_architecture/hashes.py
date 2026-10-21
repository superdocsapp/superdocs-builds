"""Deterministic hashes for structured profile sections."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from job_architecture.models import PROFILE_SECTION_IDS, RoleProfile


def canonical_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def hash_payload(value: Any) -> str:
    encoded = canonical_dumps(value).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_section(profile: RoleProfile, section_id: str) -> str:
    return hash_payload(profile.section_value(section_id))


def hash_all_sections(profile: RoleProfile) -> dict[str, str]:
    return {section_id: hash_section(profile, section_id) for section_id in PROFILE_SECTION_IDS}
