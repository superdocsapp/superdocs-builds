"""Ground-truth loading helpers for the evaluation layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class GroundTruthLoader:
    """Load benchmark ground-truth JSON fixtures from the evaluation directory."""

    def __init__(self, ground_truth_dir: str | Path | None = None):
        base_dir = Path(ground_truth_dir) if ground_truth_dir is not None else Path(__file__).resolve().parents[2] / "evaluation" / "ground_truth"
        self.ground_truth_dir = Path(base_dir)

    def list_available(self) -> list[str]:
        """Return the available ground-truth JSON file names."""
        if not self.ground_truth_dir.exists():
            return []
        return sorted(
            path.stem
            for path in self.ground_truth_dir.glob("*.json")
            if path.is_file()
        )

    def load(self, family_name: str) -> dict[str, Any]:
        """Load the ground-truth JSON for a family by name or stem."""
        normalized = family_name.strip()
        candidates = [
            f"{normalized}.json",
            f"{normalized}_ground_truth.json",
            f"{normalized.lower()}.json",
            f"{normalized.lower()}_ground_truth.json",
        ]
        for candidate in candidates:
            path = self.ground_truth_dir / candidate
            if path.exists():
                with path.open("r", encoding="utf-8") as handle:
                    return json.load(handle)

        for path in sorted(self.ground_truth_dir.glob("*.json")):
            loaded = json.loads(path.read_text(encoding="utf-8"))
            family_id = str(loaded.get("document_family", "")).strip().lower()
            if family_id == normalized.lower():
                return loaded
            if family_id.replace("_", " ") == normalized.lower().replace("_", " "):
                return loaded

        raise FileNotFoundError(f"Ground truth not found for family '{family_name}' in {self.ground_truth_dir}")

    def load_all(self) -> dict[str, dict[str, Any]]:
        """Load every ground-truth JSON fixture and return a mapping by document family."""
        result: dict[str, dict[str, Any]] = {}
        for path in sorted(self.ground_truth_dir.glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            family_name = str(payload.get("document_family") or path.stem)
            result[family_name] = payload
        return result


def load_ground_truth(family_name: str, ground_truth_dir: str | Path | None = None) -> dict[str, Any]:
    """Convenience wrapper around the default ground-truth loader."""
    return GroundTruthLoader(ground_truth_dir).load(family_name)


def load_all_ground_truths(ground_truth_dir: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load all evaluation ground-truth fixtures."""
    return GroundTruthLoader(ground_truth_dir).load_all()
