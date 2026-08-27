"""Loading the inspection catalogue and the severity scale from ``config/``.

These are data files, not enums in code, so a firm that inspects seven systems or grades on
four levels edits YAML. The loader is strict: an unknown system key or severity key is an
error naming both the offending value and the valid set, because a silently dropped finding
in an inspection report is the worst possible failure mode.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

from inspection_report.domain.models import InspectionSystem, Severity


class CatalogueError(Exception):
    """The catalogue could not be loaded, or something referenced a key it does not define."""


def config_dir() -> Path:
    """Where the YAML lives. Overridable so tests can point at a fixture directory."""
    return Path(os.environ.get("INSPECTION_CONFIG_DIR", "config"))


def _load(name: str, key: str) -> list[dict[str, object]]:
    path = config_dir() / name
    if not path.exists():
        raise CatalogueError(
            f"{path} not found. The report catalogue lives in config/; set "
            f"INSPECTION_CONFIG_DIR if it lives elsewhere."
        )
    data = yaml.safe_load(path.read_text()) or {}
    rows = data.get(key)
    if not isinstance(rows, list) or not rows:
        raise CatalogueError(f"{path} must contain a non-empty '{key}:' list")
    return rows


@lru_cache(maxsize=1)
def systems() -> tuple[InspectionSystem, ...]:
    """Every inspection system, **in report order**. That order is the report's order."""
    out = tuple(InspectionSystem.model_validate(r) for r in _load("systems.yaml", "systems"))
    keys = [s.key for s in out]
    if len(set(keys)) != len(keys):
        raise CatalogueError(f"duplicate system keys in systems.yaml: {keys}")
    return out


@lru_cache(maxsize=1)
def severities() -> tuple[Severity, ...]:
    """Every severity level, ordered by rank — most urgent first."""
    out = tuple(
        sorted(
            (Severity.model_validate(r) for r in _load("severity.yaml", "severities")),
            key=lambda s: s.rank,
        )
    )
    keys = [s.key for s in out]
    if len(set(keys)) != len(keys):
        raise CatalogueError(f"duplicate severity keys in severity.yaml: {keys}")
    return out


def system(key: str) -> InspectionSystem:
    for s in systems():
        if s.key == key:
            return s
    raise CatalogueError(
        f"unknown inspection system {key!r}. Valid keys: {[s.key for s in systems()]}. "
        f"Add it to config/systems.yaml to introduce a new one."
    )


def severity(key: str) -> Severity:
    for s in severities():
        if s.key == key:
            return s
    raise CatalogueError(
        f"unknown severity {key!r}. Valid keys: {[s.key for s in severities()]}. "
        f"Add it to config/severity.yaml to introduce a new one."
    )


def reset_cache() -> None:
    """Drop memoised catalogues. Used by tests that swap the config directory."""
    systems.cache_clear()
    severities.cache_clear()
