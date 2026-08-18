import argparse
import json
from pathlib import Path

from backend.fact_loader import load_game_facts
from backend.fact_model import GameFacts


def _join_features(features: list[str], limit: int = 3) -> str:
    selected = [feature.strip() for feature in features[:limit] if feature.strip()]
    if not selected:
        return ""
    return "Key features include: " + " ".join(selected)


def generate_press_kit(facts: GameFacts) -> dict:
    """Generate a press kit using only information present in GameFacts."""
    game = facts.game
    core = facts.core_description.strip()

    # The core description is the canonical one-line statement. Longer forms
    # are composed from source-backed fields rather than game-specific prose.
    one_line = core
    feature_summary = _join_features(facts.features)

    paragraph_parts = [core]
    if feature_summary:
        paragraph_parts.append(feature_summary)
    paragraph = " ".join(paragraph_parts)

    long_parts = [
        core,
        f"Developed by {game.studio}, {game.title} is an {game.genre}." if game.genre[:1].lower() in "aeiou" else f"Developed by {game.studio}, {game.title} is a {game.genre}.",
        facts.history,
        facts.inspiration,
    ]
    if facts.features:
        long_parts.append("Key features include: " + " ".join(facts.features))
    long_form = " ".join(part.strip() for part in long_parts if part.strip())

    return {
        "title": game.title,
        "fact_sheet": {
            "studio": game.studio,
            "release_date": game.release_date,
            "platforms": list(game.platforms),
            "price": game.price,
            "availability": game.availability,
        },
        "descriptions": {
            "one_line": one_line,
            "one_paragraph": paragraph,
            "long_form": long_form,
        },
        "features": list(facts.features),
        "history_and_inspiration": {
            "history": facts.history,
            "inspiration": facts.inspiration,
        },
        "quote": {
            "text": facts.quote.text,
            "attribution": facts.quote.attribution,
        },
        "awards": [
            {"name": award.name, "year": award.year}
            for award in facts.awards
        ],
        "coverage": [
            {
                "publication": item.publication,
                "headline": item.headline,
                "url": item.url,
            }
            for item in facts.coverage
        ],
        "asset_index": [
            {
                "filename": asset.filename,
                "type": asset.type,
                "caption": asset.caption,
                "credit": asset.credit,
            }
            for asset in facts.assets
        ],
        "provenance": {
            "fact_sheet": "game.*",
            "descriptions.core": "descriptions.core",
            "features": "features[]",
            "history_and_inspiration.history": "history_and_inspiration.history",
            "history_and_inspiration.inspiration": "history_and_inspiration.inspiration",
            "quote": "quote.*",
            "awards": "awards[]",
            "coverage": "coverage[]",
            "asset_index": "assets[]",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a grounded game press kit.")
    parser.add_argument("--input", default="sample-data/emberfall.json")
    parser.add_argument("--output-dir", default="output")
    args = parser.parse_args()

    facts = load_game_facts(args.input)
    press_kit = generate_press_kit(facts)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{facts.game.title.lower()}_press_kit.json"
    output_path.write_text(
        json.dumps(press_kit, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Saved press kit to: {output_path}")


if __name__ == "__main__":
    main()
