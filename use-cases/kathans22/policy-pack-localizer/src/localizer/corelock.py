"""Normalises and hashes core sections to lock and verify their identity."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parents[2] / "state"

# Curly/smart quote variants -> straight ASCII equivalents.
_QUOTE_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
}

# Dash-family characters editors substitute for one another via smart-dash
# autocorrect (hyphen-minus, hyphen, non-breaking hyphen, figure dash,
# en dash, em dash, minus sign) -> one canonical hyphen-minus.
_DASH_CHARS = "-‐‑‒–—−"
_DASH_RE = re.compile(f"[{_DASH_CHARS}]")

# Non-breaking / figure / thin / narrow-no-break space variants -> a regular space.
_SPACE_CHARS = "    "
_SPACE_RE = re.compile(f"[{_SPACE_CHARS}]")

_LIST_MARKER_RE = re.compile(r"^([ \t]*)[-*•][ \t]+", re.MULTILINE)
_BLANK_RUN_RE = re.compile(r"\n[ \t]*\n(?:[ \t]*\n)*")
_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)
_INLINE_WS_RE = re.compile(r"[ \t]+")


def normalise(text: str) -> str:
    """Canonicalise text so cosmetic round-trip noise never registers as a change.

    Used at lock time and at verify time, and nowhere else in this codebase.
    The contract:

    1. Unicode-normalise to NFC, so an editor's combining-character
       re-encoding of an accented letter compares equal to the original.
    2. Collapse all line-ending styles (\\r\\n, \\r) to \\n.
    3. Map curly/smart quotes to straight ASCII quotes.
    4. Map all dash-family characters (hyphen-minus, en dash, em dash,
       minus sign) to one canonical hyphen-minus, since editors' smart-dash
       autocorrect substitutes freely between them.
    5. Map non-breaking and other Unicode space variants to a regular space.
    6. Canonicalise a line-leading list marker (-, *, or bullet, plus
       whitespace) to "- ", preserving indentation.
    7. Collapse any run of blank lines to exactly one blank line.
    8. Strip trailing whitespace from every line.
    9. Collapse runs of horizontal whitespace within a line to one space.
    10. Strip leading and trailing whitespace from the whole text.

    Case is deliberately left untouched: a capitalisation change may be a
    real edit (a defined term losing its capital, for example) and must
    stay detectable.

    What this gives up: a change that is *purely* one of the above — a
    quote-style swap, a dash-glyph swap, a bullet-marker swap, a
    whitespace-only edit, or an NFC/NFD re-encoding — is indistinguishable
    from no edit at all once normalised. Any change to actual wording,
    numbers, or word order leaves the alphanumeric content stream untouched
    and is still detected.
    """
    normalised = unicodedata.normalize("NFC", text)
    normalised = normalised.replace("\r\n", "\n").replace("\r", "\n")
    for curly, straight in _QUOTE_MAP.items():
        normalised = normalised.replace(curly, straight)
    normalised = _DASH_RE.sub("-", normalised)
    normalised = _SPACE_RE.sub(" ", normalised)
    normalised = _LIST_MARKER_RE.sub(r"\1- ", normalised)
    normalised = _BLANK_RUN_RE.sub("\n\n", normalised)
    normalised = _TRAILING_WS_RE.sub("", normalised)
    normalised = _INLINE_WS_RE.sub(" ", normalised)
    return normalised.strip()


def lock(sections: list[dict], core_version: int, language: str) -> dict:
    """Hash each core section and derive one core_hash over all of them.

    `sections` must already be filtered to core-role sections, in document
    order — this function does not consult the manifest to decide what is
    core. Each section's body is hashed individually (SHA-256 of its
    normalised text), and core_hash is the SHA-256 of the normalised
    section bodies joined in order, so any reordering of core sections
    changes core_hash even if no individual section body changed.
    """
    section_hashes = {}
    ordered_normalised = []
    for section in sections:
        normalised_body = normalise(section["body"])
        section_hashes[str(section["number"])] = hashlib.sha256(
            normalised_body.encode("utf-8")
        ).hexdigest()
        ordered_normalised.append(normalised_body)

    core_hash = hashlib.sha256(
        "\n\n".join(ordered_normalised).encode("utf-8")
    ).hexdigest()

    return {
        "core_version": core_version,
        "language": language,
        "section_numbers": [s["number"] for s in sections],
        "section_hashes": section_hashes,
        "core_hash": core_hash,
    }


def _lock_path(core_version: int, language: str) -> Path:
    return STATE_DIR / f"core-lock-v{core_version}-{language}.json"


def save_lock(lock_data: dict) -> Path:
    """Write a lock dict to state/core-lock-v{version}-{lang}.json."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _lock_path(lock_data["core_version"], lock_data["language"])
    path.write_text(json.dumps(lock_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_lock(core_version: int, language: str) -> dict:
    """Read back the lock file for a given core_version and language."""
    path = _lock_path(core_version, language)
    return json.loads(path.read_text(encoding="utf-8"))


def lock_exists(core_version: int, language: str) -> bool:
    """True if a lock file for this core_version/language is already on disk.

    Used as the artifact-presence half of an idempotency check (paired with
    a ledger content_key check) — a persisted ledger entry alone is not
    proof the lock survived, e.g. a wiped state/ directory.
    """
    return _lock_path(core_version, language).exists()


def verify(sections: list[dict], lock_data: dict) -> dict:
    """Recompute core section hashes and compare against a lock.

    Names exactly which section numbers diverged, are missing from
    `sections` but present in the lock, or are present in `sections` but
    not covered by the lock — not just a pass/fail boolean.
    """
    lock_numbers = lock_data["section_numbers"]
    section_by_number = {s["number"]: s for s in sections}

    missing_sections = [n for n in lock_numbers if n not in section_by_number]
    unexpected_sections = [
        s["number"] for s in sections if s["number"] not in lock_numbers
    ]

    diverged_sections = []
    for number in lock_numbers:
        section = section_by_number.get(number)
        if section is None:
            continue
        actual_hash = hashlib.sha256(
            normalise(section["body"]).encode("utf-8")
        ).hexdigest()
        expected_hash = lock_data["section_hashes"][str(number)]
        if actual_hash != expected_hash:
            diverged_sections.append(number)

    core_hash_matches = False
    if not missing_sections and not unexpected_sections:
        ordered_present = [section_by_number[n] for n in lock_numbers]
        recomputed = lock(ordered_present, lock_data["core_version"], lock_data["language"])
        core_hash_matches = recomputed["core_hash"] == lock_data["core_hash"]

    passed = (
        not diverged_sections
        and not missing_sections
        and not unexpected_sections
        and core_hash_matches
    )

    return {
        "passed": passed,
        "diverged_sections": diverged_sections,
        "missing_sections": missing_sections,
        "unexpected_sections": unexpected_sections,
        "core_hash_matches": core_hash_matches,
    }
