"""Write a printable welcome-card HTML file from canonical content."""

from __future__ import annotations

import argparse
from pathlib import Path

from content_generator import get_property_canonical_content
from mock_data import load_mock_catalog
from welcome_card_generator import generate_welcome_card_html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--property", default="green", choices=("green", "blue"))
    parser.add_argument("--language", default="en", choices=("en", "kn"))
    parser.add_argument("--output", type=Path, default=Path("output") / "welcome_card.html")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(generate_welcome_card_html(get_property_canonical_content(load_mock_catalog(), args.property, args.language)), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
