"""Load and validate deck-manifest.yaml, product.yaml, and vertical knowledge files.

Adding a vertical is a new YAML under config/verticals/ — zero code changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REQUIRED_VERTICAL_FIELDS: tuple[str, ...] = (
    "vertical",
    "buyer_role",
    "regulatory_trigger",
    "document_pain",
    "typical_objection",
    "proof_point",
    "terminology",
)

REQUIRED_PRODUCT_FIELDS: tuple[str, ...] = (
    "name",
    "positioning",
    "capabilities",
    "differentiator",
)

REQUIRED_SECTION_FIELDS: tuple[str, ...] = (
    "number",
    "title",
    "weight",
    "image_eligible",
)

ALLOWED_WEIGHTS: frozenset[str] = frozenset({"shared", "vertical"})


class ManifestValidationError(ValueError):
    """Config failed validation; message names the specific gap."""


def project_root() -> Path:
    """use-cases/kathans22/pitch-deck-narrative/ (parent of src/)."""
    return Path(__file__).resolve().parents[2]


def config_dir(root: Path | None = None) -> Path:
    return (root or project_root()) / "config"


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise FileNotFoundError(f"config file not found: {path}")
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        raise ValueError(f"config file is empty: {path}")
    return data


def load_deck_manifest(root: Path | None = None) -> dict[str, Any]:
    """Load config/deck-manifest.yaml."""
    path = config_dir(root) / "deck-manifest.yaml"
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"deck manifest must be a mapping: {path}")
    return data


def load_product(root: Path | None = None) -> dict[str, Any]:
    """Load config/product.yaml."""
    path = config_dir(root) / "product.yaml"
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise ValueError(f"product config must be a mapping: {path}")
    return data


def load_verticals(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Load every *.yaml under config/verticals/. Keyed by stem (e.g. legal)."""
    directory = config_dir(root) / "verticals"
    if not directory.is_dir():
        raise FileNotFoundError(f"verticals directory not found: {directory}")

    verticals: dict[str, dict[str, Any]] = {}
    for path in sorted(directory.glob("*.yaml")):
        data = _read_yaml(path)
        if not isinstance(data, dict):
            raise ValueError(f"vertical file must be a mapping: {path}")
        verticals[path.stem] = data
    return verticals


def load_all(root: Path | None = None) -> dict[str, Any]:
    """Load manifest, product, and all vertical files (no validation)."""
    return {
        "manifest": load_deck_manifest(root),
        "product": load_product(root),
        "verticals": load_verticals(root),
    }


def _require_non_empty_str(value: Any, field_path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ManifestValidationError(f"missing or empty required field: {field_path}")


def validate_deck_manifest(manifest: dict[str, Any]) -> None:
    """Section numbers unique and contiguous; weight/image_eligible rules."""
    sections = manifest.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ManifestValidationError("missing or empty required field: sections")

    numbers: list[int] = []
    for index, section in enumerate(sections):
        prefix = f"sections[{index}]"
        if not isinstance(section, dict):
            raise ManifestValidationError(f"{prefix} must be a mapping")

        for field in REQUIRED_SECTION_FIELDS:
            if field not in section:
                raise ManifestValidationError(
                    f"missing required field: {prefix}.{field}"
                )

        number = section["number"]
        if not isinstance(number, int):
            raise ManifestValidationError(
                f"sections[{index}].number must be an integer, got {type(number).__name__}"
            )
        numbers.append(number)

        _require_non_empty_str(section["title"], f"{prefix}.title")

        weight = section["weight"]
        if weight not in ALLOWED_WEIGHTS:
            raise ManifestValidationError(
                f"sections[{index}].weight must be one of "
                f"{sorted(ALLOWED_WEIGHTS)}, got {weight!r}"
            )

        image_eligible = section["image_eligible"]
        if not isinstance(image_eligible, bool):
            raise ManifestValidationError(
                f"sections[{index}].image_eligible must be a boolean, "
                f"got {type(image_eligible).__name__}"
            )
        # Meaningful only on vertical sections in this build (proof / ROI).
        if image_eligible and weight != "vertical":
            raise ManifestValidationError(
                f"sections[{index}].image_eligible is true but weight is "
                f"{weight!r}; image_eligible is only meaningful on vertical sections"
            )

    if len(numbers) != len(set(numbers)):
        raise ManifestValidationError(
            f"section numbers must be unique, got {numbers}"
        )

    expected = list(range(1, len(numbers) + 1))
    if sorted(numbers) != expected:
        raise ManifestValidationError(
            f"section numbers must be contiguous from 1..{len(numbers)}, "
            f"got {sorted(numbers)}"
        )


def validate_product(product_doc: dict[str, Any]) -> None:
    product = product_doc.get("product")
    if not isinstance(product, dict):
        raise ManifestValidationError("missing required field: product")

    for field in REQUIRED_PRODUCT_FIELDS:
        if field not in product:
            raise ManifestValidationError(f"missing required field: product.{field}")

    _require_non_empty_str(product["name"], "product.name")
    _require_non_empty_str(product["positioning"], "product.positioning")
    _require_non_empty_str(product["differentiator"], "product.differentiator")

    capabilities = product["capabilities"]
    if not isinstance(capabilities, list) or not capabilities:
        raise ManifestValidationError(
            "missing or empty required field: product.capabilities"
        )
    for index, item in enumerate(capabilities):
        _require_non_empty_str(item, f"product.capabilities[{index}]")


def validate_vertical(stem: str, data: dict[str, Any]) -> None:
    for field in REQUIRED_VERTICAL_FIELDS:
        if field not in data:
            raise ManifestValidationError(
                f"vertical {stem!r} missing required field: {field}"
            )

    _require_non_empty_str(data["vertical"], f"vertical[{stem}].vertical")
    _require_non_empty_str(data["buyer_role"], f"vertical[{stem}].buyer_role")
    _require_non_empty_str(
        data["regulatory_trigger"], f"vertical[{stem}].regulatory_trigger"
    )
    _require_non_empty_str(data["document_pain"], f"vertical[{stem}].document_pain")
    _require_non_empty_str(
        data["typical_objection"], f"vertical[{stem}].typical_objection"
    )
    _require_non_empty_str(data["proof_point"], f"vertical[{stem}].proof_point")

    terminology = data["terminology"]
    if not isinstance(terminology, list) or not terminology:
        raise ManifestValidationError(
            f"vertical {stem!r} missing or empty required field: terminology"
        )
    if not (5 <= len(terminology) <= 8):
        raise ManifestValidationError(
            f"vertical {stem!r} field terminology must have 5-8 terms, "
            f"got {len(terminology)}"
        )
    for index, term in enumerate(terminology):
        _require_non_empty_str(term, f"vertical[{stem}].terminology[{index}]")


def validate_all(
    manifest: dict[str, Any],
    product: dict[str, Any],
    verticals: dict[str, dict[str, Any]],
) -> None:
    validate_deck_manifest(manifest)
    validate_product(product)
    if not verticals:
        raise ManifestValidationError("missing required field: verticals (no YAML files)")
    for stem, data in verticals.items():
        validate_vertical(stem, data)


def load_validated(root: Path | None = None) -> dict[str, Any]:
    """Load all config and fail loudly naming any specific gap."""
    bundle = load_all(root)
    validate_all(bundle["manifest"], bundle["product"], bundle["verticals"])
    return bundle
