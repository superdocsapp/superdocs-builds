"""Print a listing description generated from canonical property content."""

from __future__ import annotations

import argparse

from content_generator import get_property_canonical_content
from listing_generator import generate_listing_description
from mock_data import load_mock_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--property", default="green", choices=("green", "blue"))
    parser.add_argument("--language", default="en", choices=("en", "kn"))
    args = parser.parse_args()
    print(generate_listing_description(get_property_canonical_content(load_mock_catalog(), args.property, args.language)))


if __name__ == "__main__":
    main()
