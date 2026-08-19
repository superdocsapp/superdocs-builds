from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .db import Database
from .service import BenchmarkService


def main() -> None:
    settings = Settings.from_env()
    manifest = Path(__file__).resolve().parents[1] / "outputs" / "benchmark_corpus" / "benchmark_manifest.json"
    result = BenchmarkService(Database(settings.db_path), None).import_corpus(manifest)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
