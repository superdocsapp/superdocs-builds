#!/usr/bin/env python3
"""CLI for generating one sales battlecard against a fictional competitor.

Usage:
    python cli.py \
        --api-key sk_... \
        --competitor "Zephyr Analytics" \
        --pitch "Sells itself as the fastest dashboard to set up, no engineering needed." \
        --win "Our reports stay accurate when the underlying data model changes; theirs silently drift." \
        --dont-win "Their onboarding is genuinely faster for a first dashboard out of the box."

The API key can also be set via the SUPERDOCS_API_KEY environment variable.
"""

import argparse
import os
import sys
from pathlib import Path

from battlecard.generator import CompetitorInput, generate_battlecard
from battlecard.superdocs_client import SuperDocsClient, SuperDocsError

DEFAULT_OUTPUT_DIR = Path(__file__).parent / "output"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a one-page sales battlecard against a fictional competitor.")
    parser.add_argument("--competitor", required=True, help="Fictional competitor name")
    parser.add_argument("--pitch", required=True, help="What they likely tell a prospect about themselves")
    parser.add_argument("--win", required=True, help="Where we win against them")
    parser.add_argument("--dont-win", required=True, help="Honest gaps where they're stronger")
    parser.add_argument("--api-key", default=os.getenv("SUPERDOCS_API_KEY"), help="SuperDocs API key (or set SUPERDOCS_API_KEY)")
    parser.add_argument("--format", default="docx", choices=["docx", "pdf", "html", "markdown", "txt"], help="Export format")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory to write the exported card into")
    args = parser.parse_args()

    if not args.api_key:
        print("error: no API key. Pass --api-key or set SUPERDOCS_API_KEY.", file=sys.stderr)
        return 1

    client = SuperDocsClient(api_key=args.api_key)
    competitor = CompetitorInput(
        name=args.competitor,
        likely_pitch=args.pitch,
        where_we_win=args.win,
        where_we_dont=args.dont_win,
    )

    try:
        out_path = generate_battlecard(client, competitor, Path(args.output_dir), export_format=args.format)
    except SuperDocsError as exc:
        print(f"error: SuperDocs API call failed ({exc.status_code}): {exc.body}", file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
