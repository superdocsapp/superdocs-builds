import argparse
import copy
import json
from pathlib import Path

from backend.translator import translate_descriptions, translate_features, translate_history


def localize_press_kit(source: dict, language: str) -> dict:
    """Translate narrative fields while deep-copying all protected fields."""
    return {
        "title": source["title"],
        "fact_sheet": copy.deepcopy(source["fact_sheet"]),
        "descriptions": translate_descriptions(source["descriptions"], language),
        "features": translate_features(source["features"], language),
        "history_and_inspiration": translate_history(source["history_and_inspiration"], language),
        "quote": copy.deepcopy(source["quote"]),
        "awards": copy.deepcopy(source["awards"]),
        "coverage": copy.deepcopy(source["coverage"]),
        "asset_index": copy.deepcopy(source["asset_index"]),
        "provenance": copy.deepcopy(source.get("provenance", {})),
    }


def validate_localization(source: dict, localized: dict) -> list[str]:
    errors: list[str] = []
    if set(source) != set(localized):
        errors.append("Localized press kit structure differs from the source.")
    for field in ("fact_sheet", "asset_index", "quote", "awards", "coverage"):
        if localized.get(field) != source.get(field):
            errors.append(f"{field} changed during localization.")
    for field in ("one_line", "one_paragraph", "long_form"):
        if localized.get("descriptions", {}).get(field) == source.get("descriptions", {}).get(field):
            errors.append(f"descriptions.{field} was not localized.")
    if localized.get("features") == source.get("features"):
        errors.append("features were not localized.")
    if localized.get("history_and_inspiration") == source.get("history_and_inspiration"):
        errors.append("history_and_inspiration was not localized.")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Localize a press kit.")
    parser.add_argument("--input", default="output/emberfall_press_kit.json")
    parser.add_argument("--output", default="output/emberfall_press_kit_es.json")
    parser.add_argument("--language", default="Spanish")
    args = parser.parse_args()
    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    localized = localize_press_kit(source, args.language)
    errors = validate_localization(source, localized)
    if errors:
        raise RuntimeError("Localization validation failed: " + "; ".join(errors))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(localized, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Localization validated and saved to: {output}")


if __name__ == "__main__":
    main()
