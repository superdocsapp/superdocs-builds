"""
Convenience wrapper for local dev: seeds the DB from the sample JSON
fixture. This is now a thin call into the real import adapter
(case_import.py) -- kept around under its original name so existing docs
and habits keep working. For anything beyond local dev/demo, use
scripts/import_cases.py directly against a real CaseSource.

Usage:
    python scripts/seed_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from case_status_desk.case_import import JsonFileCaseSource, sync_cases
from case_status_desk.db import init_db, get_session

if __name__ == "__main__":
    init_db()
    sample_path = Path(__file__).resolve().parents[1] / "data" / "sample_cases.json"
    count = sync_cases(JsonFileCaseSource(sample_path), get_session)
    print(f"Seeded database with {count} case(s) from data/sample_cases.json")
