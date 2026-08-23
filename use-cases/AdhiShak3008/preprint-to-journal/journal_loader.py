"""
journal_loader.py
Load and validate journal profiles from JSON files in journal_profiles/.

A new journal is added by creating a new JSON file — no code changes needed.
"""

import json
import os

PROFILES_DIR = os.path.join(os.path.dirname(__file__), "journal_profiles")

REQUIRED_FIELDS = [
    "id",
    "name",
    "section_order",
    "reference_style",
    "figure_placement",
    "table_placement",
    "blinded_review",
    "required_declarations",
]


class JournalProfileError(Exception):
    """Raised when a journal profile is missing required fields or is malformed."""
    pass


def load_profile(journal_id):
    """
    Load a journal profile by its id string.

    Raises:
        JournalProfileError if the file is missing, malformed, or invalid.
    """
    path = os.path.join(PROFILES_DIR, f"{journal_id}.json")
    if not os.path.exists(path):
        raise JournalProfileError(
            f"No journal profile found for '{journal_id}'. "
            f"Expected file: {path}"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise JournalProfileError(
            f"Journal profile '{journal_id}' contains invalid JSON: {e}"
        )
    _validate(data, journal_id)
    return data


def list_profiles():
    """
    Return a list of all available journal profiles as dicts with
    keys: id, name.
    """
    profiles = []
    if not os.path.isdir(PROFILES_DIR):
        return profiles
    for filename in sorted(os.listdir(PROFILES_DIR)):
        if not filename.endswith(".json"):
            continue
        journal_id = filename[:-5]
        try:
            profile = load_profile(journal_id)
            profiles.append({"id": profile["id"], "name": profile["name"]})
        except JournalProfileError:
            pass  # skip malformed profiles in listing
    return profiles


def _validate(data, journal_id):
    """Raise JournalProfileError if required fields are missing or wrong type."""
    for field in REQUIRED_FIELDS:
        if field not in data:
            raise JournalProfileError(
                f"Journal profile '{journal_id}' is missing required field: '{field}'"
            )
    if not isinstance(data["section_order"], list):
        raise JournalProfileError(
            f"Journal profile '{journal_id}': 'section_order' must be a list."
        )
    if not isinstance(data["blinded_review"], bool):
        raise JournalProfileError(
            f"Journal profile '{journal_id}': 'blinded_review' must be a boolean."
        )
    if not isinstance(data["required_declarations"], list):
        raise JournalProfileError(
            f"Journal profile '{journal_id}': 'required_declarations' must be a list."
        )
