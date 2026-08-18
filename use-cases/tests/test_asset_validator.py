from pathlib import Path

from backend.asset_validator import validate_assets_exist
from backend.fact_loader import load_game_facts

ROOT = Path(__file__).resolve().parent.parent


def test_all_declared_assets_exist():
    facts = load_game_facts(str(ROOT / "sample-data/emberfall.json"))
    assert validate_assets_exist(facts, ROOT / "sample-data/assets") == []


def test_missing_asset_is_reported(tmp_path):
    facts = load_game_facts(str(ROOT / "sample-data/emberfall.json"))
    (tmp_path / "emberfall-key-art.jpg").write_bytes(b"placeholder")
    missing = validate_assets_exist(facts, tmp_path)
    assert "emberfall-beacon.jpg" in missing
    assert len(missing) == 3
