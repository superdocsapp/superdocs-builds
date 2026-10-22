from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .db import Database
from .public_snapshot import export_public_snapshot


def main() -> None:
    settings=Settings.from_env()
    destination=Path(__file__).resolve().parents[1]/"outputs"/"final_run"/"public_snapshot.json"
    print(json.dumps(export_public_snapshot(Database(settings.db_path),destination),indent=2))


if __name__ == "__main__":
    main()
