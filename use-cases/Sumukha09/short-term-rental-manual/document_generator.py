"""Printable HTML payloads for SuperDocs document operations.

The module generates HTML only.  SuperDocs remains responsible for upload,
editing, and PDF export in the live workflow.
"""

from __future__ import annotations

import base64
from html import escape
from pathlib import Path
from typing import Any


def image_as_data_uri(path: str | Path) -> str:
    """Load a real image and return an embeddable data URI.

    The mime type is determined from file bytes, not its suffix, so source
    photographs retain their correct type even when an operator renames them.
    """
    image_path = Path(path)
    payload = image_path.read_bytes()
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        mime_type = "image/png"
    elif payload.startswith(b"\xff\xd8\xff"):
        mime_type = "image/jpeg"
    else:
        raise ValueError(f"Unsupported image format: {image_path}")
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _text(value: Any) -> str:
    return escape(str(value))


def _section(title: str, body: str, *, section_class: str = "") -> str:
    return f'<section class="manual-section {section_class}"><h2>{_text(title)}</h2>{body}</section>'


def generate_manual_html(content: dict[str, Any]) -> str:
    """Create a complete guest-manual HTML payload from canonical content."""
    labels = content["labels"]
    property_data = content["property"]
    photos = content["photos"]
    cover_image = image_as_data_uri(photos[0]["path"])

    overview = "".join(
        f'<div class="stat"><strong>{_text(label)}</strong><span>{_text(value)}</span></div>'
        for label, value in (
            (labels["property_type"], property_data["property_type"]),
            (labels["bedrooms"], property_data["bedrooms"]),
            (labels["bathrooms"], property_data["bathrooms"]),
            (labels["maximum_guests"], property_data["maximum_guests"]),
        )
    )
    arrival = (
        f'<div class="detail-grid"><p><strong>{_text(labels["check_in"])}:</strong> {_text(property_data["check_in"])}</p>'
        f'<p><strong>{_text(labels["access_instructions"])}:</strong> {_text(property_data["access_instructions"])}</p></div>'
    )
    wifi = (
        f'<div class="wifi-card"><p>{_text(labels["network"])}</p><strong>{_text(property_data["wifi_network"])}</strong>'
        f'<p>{_text(labels["password"])}</p><strong>{_text(property_data["wifi_password"])}</strong></div>'
    )
    appliance_rows = "".join(
        f'<article class="item"><h3>{_text(appliance["name"])}</h3><p>{_text(appliance["instructions"])}</p></article>'
        for appliance in content["appliances"]
    )
    rules = "".join(
        f'<article class="rule"><h3>{_text(block["title"])}</h3><p>{_text(block["content"])}</p></article>'
        for block in content["shared_blocks"]
        if block["block_type"] in {"house_rule", "checkout_policy"}
    )
    rules += f'<article class="rule"><h3>{_text(labels["maximum_guests"])}</h3><p>{_text(property_data["maximum_guests"])} guests may stay at the property.</p></article>'
    recommendations = "".join(
        f'<article class="item"><h3>{_text(rec["category"])} · {_text(rec["name"])}</h3><p>{_text(rec["description"])} <span class="distance">{_text(rec["distance"])}</span></p></article>'
        for rec in content["local_recommendations"]
    )
    emergency = content["emergency_information"]
    emergency_body = (
        '<div class="emergency-card">'
        f'<p><strong>{_text(labels["emergency_number"])}:</strong> {_text(emergency["emergency_number"])}</p>'
        f'<p><strong>{_text(labels["property_manager"])}:</strong> {_text(emergency["property_manager"])}</p>'
        f'<p><strong>{_text(labels["hospital"])}:</strong> {_text(emergency["hospital"])}</p>'
        "</div>"
    )
    emergency_procedure = next(
        (block["content"] for block in content["shared_blocks"] if block["block_type"] == "emergency_procedure"), ""
    )
    photo_gallery = "".join(
        f'<figure><img src="{image_as_data_uri(photo["path"])}" alt="{_text(photo["alt_text"])}"><figcaption>{_text(photo["caption"])}</figcaption></figure>'
        for photo in photos
    )
    map_diagram = content["map_diagram"]
    map_body = (
        f'<figure class="map"><img src="{image_as_data_uri(map_diagram["path"])}" alt="{_text(map_diagram["alt_text"])}">'
        f'<figcaption>{_text(map_diagram["caption"])}</figcaption></figure>'
    )
    checkout = next(
        (block["content"] for block in content["shared_blocks"] if block["block_type"] == "checkout_policy"), ""
    )

    return f"""<!doctype html>
<html lang="{_text(content['language'])}">
<head>
<meta charset="utf-8">
<title>{_text(content['title'])} — { _text(labels['guest_house_manual']) }</title>
<style>
  @page {{ size: A4; margin: 16mm; }}
  * {{ box-sizing: border-box; }} body {{ color: #25322d; font: 11pt/1.55 Arial, sans-serif; margin: 0; }}
  h1, h2, h3 {{ color: #1f6548; line-height: 1.2; }} h1 {{ font-size: 32pt; margin: 0; }} h2 {{ border-bottom: 2px solid #bed8c9; font-size: 20pt; margin: 0 0 12px; padding-bottom: 6px; }} h3 {{ font-size: 12pt; margin: 0 0 5px; }} p {{ margin: 0 0 9px; }}
  .cover {{ align-items: flex-end; background: linear-gradient(0deg, rgba(16,49,35,.88), rgba(16,49,35,.04)), url('{cover_image}') center/cover; color: white; display: flex; height: 265mm; padding: 25mm; page-break-after: always; }} .cover h1 {{ color: white; }} .cover p {{ font-size: 16pt; margin-top: 8px; }}
  .manual-section {{ break-inside: avoid; margin: 0 0 25px; }} .stat-grid, .detail-grid {{ display: grid; gap: 10px; grid-template-columns: repeat(2, 1fr); }} .stat {{ background: #f0f7f2; border-left: 4px solid #3b8762; padding: 10px; }} .stat strong, .stat span {{ display: block; }}
  .wifi-card {{ background: #1f6548; border-radius: 8px; color: white; max-width: 410px; padding: 15px 18px; }} .wifi-card p {{ margin: 0; opacity: .82; }} .wifi-card strong {{ display: block; font-size: 15pt; margin: 0 0 10px; }}
  .item, .rule {{ border-bottom: 1px solid #dce7df; break-inside: avoid; padding: 9px 0; }} .rule {{ background: #f8fbf8; border-left: 3px solid #70aa87; margin-bottom: 7px; padding: 10px 13px; }} .distance {{ color: #5a6a61; font-weight: bold; white-space: nowrap; }}
  .emergency-card {{ background: #fff3ef; border: 1px solid #e3a18a; border-radius: 8px; padding: 15px; }} .gallery {{ display: grid; gap: 12px; grid-template-columns: repeat(2, 1fr); }} figure {{ break-inside: avoid; margin: 0; }} figure img {{ border-radius: 5px; display: block; height: 155px; object-fit: cover; width: 100%; }} figcaption {{ color: #5a6a61; font-size: 9pt; margin-top: 4px; }} .map img {{ border: 1px solid #dce7df; height: auto; max-height: 220px; object-fit: contain; }}
  @media print {{ .manual-section {{ break-inside: avoid; }} }}
</style>
</head>
<body>
  <header class="cover"><div><h1>{_text(content['title'])}</h1><p>{_text(labels['guest_house_manual'])}</p></div></header>
  {_section(labels['welcome'], f'<p>{_text(content["welcome_message"])}</p>')}
  {_section(labels['property_overview'], f'<div class="stat-grid">{overview}</div>')}
  {_section(labels['arrival_checkin'], arrival)}
  {_section(labels['wifi'], wifi)}
  {_section(labels['appliances'], appliance_rows)}
  {_section(labels['house_rules'], rules)}
  {_section(labels['local_recommendations'], recommendations)}
  {_section(labels['emergency_information'], emergency_body + f'<p>{_text(emergency_procedure)}</p>')}
  {_section(labels['checkout'], f'<p>{_text(checkout)}</p>')}
  {_section(labels['photos'], f'<div class="gallery">{photo_gallery}</div>', section_class='page-break')}
  {_section(labels['location_map'], map_body)}
</body>
</html>"""
