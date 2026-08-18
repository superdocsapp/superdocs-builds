import json
from pathlib import Path

from backend.fact_loader import load_game_facts
from backend.fact_validator import validate_press_kit
from backend.press_kit_generator import generate_press_kit

ROOT = Path(__file__).resolve().parent.parent


def load(path: str):
    return load_game_facts(str(ROOT / "sample-data" / path))


def test_press_kit_generation_has_required_sections():
    kit = generate_press_kit(load("emberfall.json"))
    required = {"title", "fact_sheet", "descriptions", "features", "history_and_inspiration", "quote", "awards", "coverage", "asset_index", "provenance"}
    assert required.issubset(kit)


def test_fact_sheet_contains_required_fields():
    kit = generate_press_kit(load("emberfall.json"))
    assert set(kit["fact_sheet"]) == {"studio", "release_date", "platforms", "price", "availability"}


def test_three_description_lengths_exist_and_share_core():
    facts = load("emberfall.json")
    kit = generate_press_kit(facts)
    descriptions = kit["descriptions"]
    assert all(descriptions.values())
    assert len({descriptions["one_line"], descriptions["one_paragraph"], descriptions["long_form"]}) == 3
    for text in descriptions.values():
        assert facts.core_description in text
    assert len(descriptions["one_line"]) < len(descriptions["one_paragraph"]) < len(descriptions["long_form"])


def test_features_history_quote_awards_coverage_and_assets_are_source_backed():
    facts = load("emberfall.json")
    kit = generate_press_kit(facts)
    assert kit["features"] == facts.features
    assert kit["history_and_inspiration"] == {"history": facts.history, "inspiration": facts.inspiration}
    assert kit["quote"] == {"text": facts.quote.text, "attribution": facts.quote.attribution}
    assert kit["awards"] == [{"name": a.name, "year": a.year} for a in facts.awards]
    assert kit["coverage"] == [{"publication": c.publication, "headline": c.headline, "url": c.url} for c in facts.coverage]
    assert len(kit["asset_index"]) == len(facts.assets)


def test_generated_press_kit_validates():
    facts = load("emberfall.json")
    result = validate_press_kit(facts, generate_press_kit(facts))
    assert result.valid, result.issues


def test_same_generator_works_on_second_dataset():
    facts = load("ashvale.json")
    kit = generate_press_kit(facts)
    assert kit["title"] == "Ashvale"
    assert kit["fact_sheet"]["studio"] == "Copper Lantern"
    assert "Emberfall" not in json.dumps(kit)
    assert kit["asset_index"][0]["filename"] == "ashvale-key-art.jpg"
