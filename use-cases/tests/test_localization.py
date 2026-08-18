from pathlib import Path

from backend.fact_loader import load_game_facts
from backend.localizer import localize_press_kit, validate_localization
from backend.translator import translate_text
from backend.press_kit_generator import generate_press_kit

ROOT = Path(__file__).resolve().parent.parent


def test_localization_preserves_protected_sections_and_localizes_narrative():
    source = generate_press_kit(load_game_facts(str(ROOT / "sample-data" / "emberfall.json")))
    localized = localize_press_kit(source, "Spanish")
    assert validate_localization(source, localized) == []
    for field in ("fact_sheet", "asset_index", "quote", "awards", "coverage"):
        assert localized[field] == source[field]
    for field in ("one_line", "one_paragraph", "long_form"):
        assert localized["descriptions"][field] != source["descriptions"][field]
    assert localized["features"] != source["features"]
    assert localized["history_and_inspiration"] != source["history_and_inspiration"]


def test_unsupported_translation_never_silently_returns_english():
    try:
        translate_text("A narrative sentence without a verified translation.", "Spanish")
    except ValueError as exc:
        assert "No verified Spanish translation" in str(exc)
    else:
        raise AssertionError("Unsupported narrative was silently accepted")
