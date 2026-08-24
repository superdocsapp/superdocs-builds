from __future__ import annotations

import json
from pathlib import Path

from .config import Settings
from .db import Database
from .service import BenchmarkService
from .public_snapshot import import_public_snapshot


def main() -> None:
    settings = Settings.from_env()
    manifest = Path(__file__).resolve().parents[1] / "outputs" / "benchmark_corpus" / "benchmark_manifest.json"
    db=Database(settings.db_path)
    result = BenchmarkService(db, None).import_corpus(manifest)
    snapshot=Path(__file__).resolve().parents[1]/"outputs"/"final_run"/"public_snapshot.json"
    if snapshot.is_file(): result["published_snapshot"]=import_public_snapshot(db,snapshot)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
