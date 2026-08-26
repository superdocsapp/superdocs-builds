"""Loads and validates manifest.yaml and country config files."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"
MANIFEST_PATH = CONFIG_DIR / "manifest.yaml"
COUNTRIES_DIR = CONFIG_DIR / "countries"

REQUIRED_ANNEX_SLOTS = {"reporting", "legal", "escalation"}
REQUIRED_COUNTRY_FIELDS = ("country", "code", "language", "office", "safeguarding_lead")


def load_manifest(path: Path = MANIFEST_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        manifest = yaml.safe_load(f)
    _validate_manifest(manifest, path)
    return manifest


def load_country(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        country = yaml.safe_load(f)
    _validate_country(country, path)
    return country


def load_all_countries(directory: Path = COUNTRIES_DIR) -> dict:
    countries = {}
    for path in sorted(directory.glob("*.yaml")):
        country = load_country(path)
        countries[country["code"]] = country
    return countries


def _validate_manifest(manifest: dict, path: Path) -> None:
    if not manifest or "sections" not in manifest:
        raise ValueError(f"{path}: missing 'sections'")
    if "source_language" not in manifest:
        raise ValueError(f"{path}: missing 'source_language'")
    if not isinstance(manifest.get("annex_batch_size"), int) or manifest["annex_batch_size"] < 1:
        raise ValueError(
            f"{path}: 'annex_batch_size' must be a positive integer. This is a live, "
            "undocumented SuperDocs API characteristic (see evidence/superdocs-batch-limit-"
            "report.md), not a code constant — it must be set explicitly, not assumed."
        )

    sections = manifest["sections"]
    for section in sections:
        if "number" not in section:
            raise ValueError(f"{path}: a section is missing 'number'")

    numbers = [s["number"] for s in sections]
    if len(set(numbers)) != len(numbers):
        raise ValueError(f"{path}: section numbers are not unique: {numbers}")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        raise ValueError(f"{path}: section numbers are not contiguous from 1: {numbers}")

    slots_seen: dict[str, int] = {}
    for section in sections:
        number = section["number"]
        if "heading" not in section:
            raise ValueError(f"{path}: section {number} missing 'heading'")
        if "role" not in section:
            raise ValueError(f"{path}: section {number} missing 'role'")
        if section["role"] not in ("core", "annex"):
            raise ValueError(f"{path}: section {number} has unknown role '{section['role']}'")
        if section["role"] == "annex":
            slot = section.get("slot")
            if not slot:
                raise ValueError(f"{path}: annex section {number} missing 'slot'")
            if slot in slots_seen:
                raise ValueError(
                    f"{path}: slot '{slot}' is filled by both section {slots_seen[slot]} and {number}"
                )
            slots_seen[slot] = number

    missing_slots = REQUIRED_ANNEX_SLOTS - set(slots_seen)
    if missing_slots:
        raise ValueError(f"{path}: no annex section fills required slot(s): {sorted(missing_slots)}")


def _validate_country(country: dict, path: Path) -> None:
    if not country:
        raise ValueError(f"{path}: empty country file")
    for field in REQUIRED_COUNTRY_FIELDS:
        if field not in country:
            raise ValueError(f"{path}: missing required field '{field}'")
    for slot in REQUIRED_ANNEX_SLOTS:
        if not country.get(slot):
            raise ValueError(f"{path}: missing content for annex slot '{slot}'")
