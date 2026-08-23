import argparse
from pathlib import Path

from src.localizer import (
    Localizer,
    TestLocalizationProvider,
)
from src.pipeline import LocalizationPipeline
from src.superdocs_provider import (
    SuperDocsLocalizationProvider,
)


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Localize a help-centre article and "
            "swap locale-specific screenshots."
        )
    )

    parser.add_argument(
        "--input",
        required=True,
        help="Path to the source HTML article.",
    )

    parser.add_argument(
        "--locale",
        required=True,
        help="Target locale, for example es or fr.",
    )

    parser.add_argument(
        "--screenshots",
        required=True,
        help="Root directory containing locale screenshots.",
    )

    parser.add_argument(
        "--output",
        required=True,
        help="Path for the localized HTML output.",
    )

    parser.add_argument(
        "--previous",
        help=(
            "Optional previous source article. "
            "When supplied, only changed paragraphs "
            "are localized."
        ),
    )

    parser.add_argument(
    "--provider",
    choices=["demo", "superdocs"],
    default="demo",
    help="Localization provider to use.",
    )

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    screenshot_root = Path(args.screenshots)
    output_path = Path(args.output)

    source_html = input_path.read_text(
        encoding="utf-8"
    )

    previous_html = None

    if args.previous:
        previous_html = Path(
            args.previous
        ).read_text(
            encoding="utf-8"
        )

    if args.provider == "superdocs":
        provider = SuperDocsLocalizationProvider()
    else:
        provider = TestLocalizationProvider()

    localizer = Localizer(
        provider=provider,
        product_names=[
            "SuperDocs",
        ],
    )

    pipeline = LocalizationPipeline(
        localizer=localizer,
        screenshot_root=screenshot_root,
    )

    result = pipeline.localize(
        source_html=source_html,
        locale=args.locale,
        previous_source_html=previous_html,
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        result.html,
        encoding="utf-8",
    )

    print()
    print("Localization complete")
    print("---------------------")
    print(f"Locale: {args.locale}")
    print(
        "Changed paragraphs:",
        result.changed_paragraphs,
    )
    print(
        "Localized paragraphs:",
        result.localized_paragraphs,
    )
    print(
        "Screenshot replacements:",
        result.screenshot_replacements,
    )

    if result.missing_screenshots:
        print()
        print("Missing screenshots:")

        for flag in result.missing_screenshots:
            print(
                f"- Image {flag.image_index}: "
                f"{flag.source}"
            )

    print()
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()