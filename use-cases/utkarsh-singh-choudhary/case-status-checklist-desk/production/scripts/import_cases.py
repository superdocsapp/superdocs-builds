"""
Production case import: pulls from a real CaseSource and syncs into the
database. Replaces scripts/seed_db.py for anything beyond local dev.

Usage (local dev, JSON file source):
    python scripts/import_cases.py --source json --path data/sample_cases.json

Usage (real CMS via generic HTTP adapter -- requires customizing
case_import.HttpCaseSource._map() first):
    python scripts/import_cases.py --source http \
        --base-url https://your-cms.example.com/api \
        --api-key "$CMS_API_KEY"

Intended to be run as a scheduled job (cron, Render cron job, etc.) so
case data stays current, since the whole point of this service is that
checklists are recomputed from the live case state, not a stale snapshot.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from case_status_desk.case_import import JsonFileCaseSource, HttpCaseSource, sync_cases
from case_status_desk.db import init_db, get_session


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", choices=["json", "http"], required=True)
    parser.add_argument("--path", type=Path, help="Path to JSON file (for --source json)")
    parser.add_argument("--base-url", help="CMS base URL (for --source http)")
    parser.add_argument("--api-key", help="CMS API key (for --source http)")
    args = parser.parse_args(argv)

    if args.source == "json":
        if not args.path:
            parser.error("--path is required for --source json")
        source = JsonFileCaseSource(args.path)
    else:
        if not args.base_url or not args.api_key:
            parser.error("--base-url and --api-key are required for --source http")
        source = HttpCaseSource(base_url=args.base_url, api_key=args.api_key)

    init_db()
    count = sync_cases(source, get_session)
    print(f"Synced {count} case(s) from {args.source} source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
