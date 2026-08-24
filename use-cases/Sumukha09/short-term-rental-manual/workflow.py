"""Preview validation and one-shot SuperDocs live workflow helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from content_generator import get_property_canonical_content
from document_generator import generate_manual_html, image_as_data_uri
from listing_generator import generate_listing_description
from models import PropertyCatalog
from superdocs_client import SuperDocsClient
from welcome_card_generator import generate_welcome_card_html


REQUIRED_MANUAL_MARKERS = ("Wi-Fi", "Appliances", "House Rules", "Emergency Information", "Location & Map")


def build_preview(catalog: PropertyCatalog, property_id: str, language: str = "en") -> dict[str, str]:
    """Build and validate all local artifacts without contacting SuperDocs."""
    content = get_property_canonical_content(catalog, property_id, language)
    for photo in content["photos"]:
        image_as_data_uri(photo["path"])
    image_as_data_uri(content["map_diagram"]["path"])
    manual = generate_manual_html(content)
    if language == "en":
        import html
        missing = [marker for marker in REQUIRED_MANUAL_MARKERS if html.escape(marker) not in manual]
        if missing:
            raise ValueError(f"Manual is missing required sections: {', '.join(missing)}")
    return {
        "manual.html": manual,
        "listing.txt": generate_listing_description(content),
        "welcome_card.html": generate_welcome_card_html(content),
    }


def write_preview(artifacts: dict[str, str], output_dir: Path) -> list[Path]:
    """Write inspected local preview artifacts; this never invokes MCP."""
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, document in artifacts.items():
        path = output_dir / filename
        path.write_text(document, encoding="utf-8")
        paths.append(path)
    return paths


def export_manual_once(
    client: SuperDocsClient, catalog: PropertyCatalog, property_id: str, language: str = "en"
) -> dict[str, Any]:
    """Upload and export a manual once. It deliberately has no edit/retry loop."""
    content = get_property_canonical_content(catalog, property_id, language)
    uploaded = client.upload_html(
        generate_manual_html(content), filename=f"{property_id}-guest-manual-{language}.html"
    )
    exported = client.export_pdf(document_id=uploaded.document_id, session_id=uploaded.session_id)
    return {"document_id": uploaded.document_id, "session_id": uploaded.session_id, "version": uploaded.version, "export": exported}


DEFAULT_EDIT_INSTRUCTION = (
    "In the House Rules section, update the quiet hours rule to end at 8 AM instead of 7 AM. "
    "Keep every other section, image, and the page layout exactly as they are."
)


def export_manual_after_approved_edit(
    client: SuperDocsClient,
    catalog: PropertyCatalog,
    property_id: str,
    language: str = "en",
    *,
    edit_instruction: str = DEFAULT_EDIT_INSTRUCTION,
) -> dict[str, Any]:
    """Run upload -> chat_async -> approve_change -> export using only MCP tools.

    The async edit is never auto-applied: ``approve_change`` is called only after
    the proposal is confirmed to be in the ``awaiting_approval`` state.
    """
    content = get_property_canonical_content(catalog, property_id, language)
    uploaded = client.upload_html(
        generate_manual_html(content), filename=f"{property_id}-guest-manual-{language}.html"
    )
    if not uploaded.session_id:
        raise RuntimeError("SuperDocs upload returned no session_id; the async edit step cannot run.")
    pending = client.request_async_edit(session_id=uploaded.session_id, instruction=edit_instruction)
    if pending.status != "awaiting_approval":
        raise RuntimeError(
            f"Change '{pending.change_id}' reached status '{pending.status}'; "
            "refusing to approve anything that is not awaiting_approval."
        )
    approved = client.approve_change(session_id=uploaded.session_id, change_id=pending.change_id)
    exported = client.export_pdf(document_id=uploaded.document_id, session_id=uploaded.session_id)
    return {
        "document_id": uploaded.document_id,
        "session_id": uploaded.session_id,
        "version": uploaded.version,
        "change_id": pending.change_id,
        "status_before_approval": pending.status,
        "proposed_change": pending.proposed_change,
        "approved": approved,
        "export": exported,
    }
