import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from techpack.generator import generate_tech_pack_html
from techpack.superdocs_client import send_edit, approve_changes, export_document, SuperDocsError
from techpack.verification import verify_measurement_table

load_dotenv()

DEFAULT_STYLE_PATH = Path("styles/classic_crew_tee.json")
OUTPUT_DIR = Path("output")


def load_style(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def get_updated_html(result: dict, fallback_html: str) -> str:
    """Returns the new HTML if the edit produced changes, otherwise falls
    back to whatever HTML we already had — a no-op is not an error."""
    changes = result.get("document_changes") or {}
    updated = changes.get("updated_html")
    if updated:
        return updated
    print("ℹ️  No changes returned (edit was a no-op) — keeping prior HTML state.")
    return fallback_html


def main():
    # Style file is now a CLI argument, not hardcoded -- this is what
    # actually proves the pipeline generalizes across garment types,
    # not just runs correctly on the one style it was built against.
    style_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_STYLE_PATH
    style = load_style(style_path)
    session_id = f"techpack-{style['style_id']}-{int(time.time())}"

    html = generate_tech_pack_html(style)
    print(f"Generated HTML for {style['style_name']} ({len(html)} chars)")

    result = send_edit(
        session_id=session_id,
        message="Format this document cleanly with a professional letterhead style. Do not change any numbers in the measurement table.",
        document_html=html,
    )
    print("Chat response:", result.get("response"))

    latest_html = get_updated_html(result, html)
    is_valid, mismatches = verify_measurement_table(latest_html, style)
    print("✅ Table verified after formatting" if is_valid else f"❌ Table mismatch after formatting: {mismatches}")

    result = send_edit(
        session_id=session_id,
        message=(
            f"Generate front-view and back-view black and white technical flat "
            f"sketches of a {style['style_name'].lower()} and insert them at the "
            f"top of the document, above the measurement table."
        ),
    )
    print("Chat response:", result.get("response"))

    latest_html = get_updated_html(result, latest_html)
    is_valid, mismatches = verify_measurement_table(latest_html, style)
    print("✅ Table still verified after image insertion" if is_valid else f"❌ Table mismatch after images: {mismatches}")

    if "<img" not in latest_html:
        print("⚠️  No <img> tag found in returned HTML — images may not have actually been inserted despite the success message.")

    changes = result.get("document_changes") or {}
    version_id = changes.get("version_id")

    if changes.get("requires_approval") or changes.get("pending_changes"):
        if not version_id:
            print("⚠️  Approval required but no version_id was returned — cannot approve. Skipping approval step.")
        else:
            try:
                approve_changes(version_id=version_id, approve_all=True)
                print("Changes approved.")
            except SuperDocsError as e:
                print(f"Approve step failed: {e}")
    else:
        print("No approval required — changes were auto-approved.")

    OUTPUT_DIR.mkdir(exist_ok=True)
    try:
        file_bytes = export_document(html=latest_html, filename=style["style_id"])
        out_path = OUTPUT_DIR / f"{style['style_id']}_techpack.docx"
        out_path.write_bytes(file_bytes)
        print(f"Exported to {out_path}")
    except SuperDocsError as e:
        print(f"Export step failed: {e}")


if __name__ == "__main__":
    main()