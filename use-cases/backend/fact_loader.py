import json
from pathlib import Path
from backend.fact_model import (
    Asset,
    Award,
    Coverage,
    GameFacts,
    GameInfo,
    Quote,
)


def load_game_facts(file_path: str) -> GameFacts:
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"Game data file not found: {file_path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    game_data = data["game"]

    game = GameInfo(
        title=game_data["title"],
        studio=game_data["studio"],
        genre=game_data["genre"],
        release_date=game_data["release_date"],
        platforms=game_data["platforms"],
        price=game_data["price"],
        availability=game_data["availability"],
    )

    quote_data = data["quote"]

    quote = Quote(
        text=quote_data["text"],
        attribution=quote_data["attribution"],
    )

    awards = [
        Award(
            name=award["name"],
            year=award["year"],
        )
        for award in data["awards"]
    ]

    coverage = [
        Coverage(
            publication=item["publication"],
            headline=item["headline"],
            url=item["url"],
        )
        for item in data["coverage"]
    ]

    assets = [
        Asset(
            filename=asset["filename"],
            type=asset["type"],
            caption=asset["caption"],
            credit=asset["credit"],
        )
        for asset in data["assets"]
    ]

    return GameFacts(
        game=game,
        core_description=data["descriptions"]["core"],
        features=data["features"],
        history=data["history_and_inspiration"]["history"],
        inspiration=data["history_and_inspiration"]["inspiration"],
        quote=quote,
        awards=awards,
        coverage=coverage,
        assets=assets,
    )


if __name__ == "__main__":
    facts = load_game_facts("sample-data/emberfall.json")

    print("Game facts loaded successfully.")
    print(f"Title: {facts.game.title}")
    print(f"Studio: {facts.game.studio}")
    print(f"Release date: {facts.game.release_date}")
    print(f"Platforms: {', '.join(facts.game.platforms)}")
    print(f"Assets: {len(facts.assets)}")
    print(f"Features: {len(facts.features)}")