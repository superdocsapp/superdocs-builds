from pathlib import Path

from backend.fact_loader import load_game_facts
from backend.fact_validator import validate_fact_sheet, validate_press_kit
from backend.press_kit_generator import generate_press_kit

ROOT = Path(__file__).resolve().parent.parent


def facts():
    return load_game_facts(str(ROOT / "sample-data/emberfall.json"))


def correct():
    return {
        "studio": "Northstar Forge",
        "release_date": "October 15, 2026",
        "platforms": ["PC", "PlayStation 5", "Xbox Series X|S"],
        "price": "$29.99",
        "availability": "Digital worldwide",
    }


def test_correct_fact_sheet_passes():
    result = validate_fact_sheet(facts(), correct())
    assert result.valid and result.issues == []


def test_each_required_fact_error_is_detected():
    for field, bad in {
        "studio": "Wrong Studio",
        "release_date": "January 1, 2030",
        "platforms": ["PC"],
        "price": "$1.00",
        "availability": "Unknown",
    }.items():
        generated = correct()
        generated[field] = bad
        result = validate_fact_sheet(facts(), generated)
        assert not result.valid
        assert {i.field for i in result.issues} == {field}


def test_all_required_fact_errors_are_detected_together():
    generated = correct()
    generated.update({
        "studio": "Wrong Studio",
        "release_date": "January 1, 2030",
        "platforms": ["PC"],
        "price": "$1.00",
        "availability": "Unknown",
    })
    result = validate_fact_sheet(facts(), generated)
    assert {i.field for i in result.issues} == set(generated)


def test_full_press_kit_validation_detects_narrative_drift():
    kit = generate_press_kit(facts())
    kit["descriptions"]["long_form"] = "Invented claim."
    result = validate_press_kit(facts(), kit)
    assert not result.valid
    assert any(i.field == "descriptions.long_form" for i in result.issues)
