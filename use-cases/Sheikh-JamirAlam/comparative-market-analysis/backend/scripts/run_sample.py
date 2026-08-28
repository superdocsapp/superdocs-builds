from pathlib import Path
import json
import argparse
import sys

sys.path.insert(0, str(Path(__file__).parents[1]))

from cma.pipeline import (
    branding_from_dict,
    generate_cma_from_saved_template,
    property_from_dict,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a sample CMA document")
    parser.add_argument("--fixture", default="suburban_single_family.json")
    parser.add_argument(
        "--format", choices=("pdf", "docx", "html"), default="pdf")
    parser.add_argument(
        "--template", default="templates/cma_saved_template.html",
        help="Template path for the saved-template workflow.",
    )
    args = parser.parse_args()

    fixture_path = Path(__file__).parents[1] / "fixtures" / args.fixture
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    subject = property_from_dict(data["subject"])
    comps = [property_from_dict(comp) for comp in data["comps"]]
    branding = branding_from_dict(data["branding"])
    output_path = Path(__file__).parents[1] / \
        "output" / f"sample_cma.{args.format}"
    result = generate_cma_from_saved_template(
        subject,
        comps,
        branding,
        output_path,
        template_path=args.template,
        export_format=args.format,
    )
    print(f"Generated {result}")


if __name__ == "__main__":
    main()
