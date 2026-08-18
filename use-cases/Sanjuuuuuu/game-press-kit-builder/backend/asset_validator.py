from pathlib import Path

from backend.fact_model import GameFacts


def validate_assets_exist(facts: GameFacts, asset_dir: str | Path) -> list[str]:
    """Ensure every asset declared by the source exists on disk."""
    root = Path(asset_dir)
    missing = [asset.filename for asset in facts.assets if not (root / asset.filename).is_file()]
    return missing
