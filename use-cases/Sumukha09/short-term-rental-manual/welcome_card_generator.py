"""One-page printable in-unit welcome cards from canonical property content."""

from __future__ import annotations

from html import escape
from typing import Any


def _quiet_hours(content: dict[str, Any]) -> str:
    for block in content["shared_blocks"]:
        if block["id"] == "quiet-hours":
            return block["content"]
    raise KeyError("A welcome card requires the quiet-hours shared block")


def generate_welcome_card_html(content: dict[str, Any]) -> str:
    """Generate a self-contained, A6 printable welcome card HTML payload."""
    labels = content["labels"]
    property_data = content["property"]
    emergency = content["emergency_information"]
    quiet_hours = _quiet_hours(content)
    text = lambda value: escape(str(value))

    return f"""<!doctype html>
<html lang="{text(content['language'])}">
<head>
<meta charset="utf-8">
<title>{text(content['title'])} — Welcome Card</title>
<style>
  @page {{ size: A6 portrait; margin: 8mm; }}
  * {{ box-sizing: border-box; }}
  body {{ background: #edf4ef; color: #1f3429; font: 10pt/1.35 Arial, sans-serif; margin: 0; }}
  .card {{ background: white; border-top: 8px solid #2d7957; border-radius: 8px; box-shadow: 0 2px 10px #cbd8ce; min-height: 132mm; padding: 12mm 10mm; }}
  h1 {{ color: #1f6548; font-size: 20pt; line-height: 1.08; margin: 0 0 3mm; }}
  .unit {{ color: #5b6f62; margin: 0 0 7mm; }}
  .wifi {{ background: #1f6548; border-radius: 6px; color: white; margin-bottom: 6mm; padding: 4mm; }}
  .wifi strong {{ display: block; font-size: 13pt; margin: 1mm 0 3mm; overflow-wrap: anywhere; }}
  .wifi span {{ font-size: 8pt; opacity: .85; text-transform: uppercase; }}
  .row {{ border-bottom: 1px solid #dce7df; padding: 3mm 0; }}
  .row strong {{ color: #1f6548; display: block; font-size: 9pt; }}
  .emergency {{ background: #fff1ec; border-left: 4px solid #d97857; margin-top: 5mm; padding: 3mm 4mm; }}
  .emergency strong {{ color: #9d3d22; }}
  @media print {{ body {{ background: white; }} .card {{ box-shadow: none; }} }}
</style>
</head>
<body>
  <main class="card">
    <h1>{text(content['title'])}</h1>
    <p class="unit">{text(property_data['unit'])} · {text(labels['guest_house_manual'])}</p>
    <section class="wifi"><span>{text(labels['wifi'])} — {text(labels['network'])}</span><strong>{text(property_data['wifi_network'])}</strong><span>{text(labels['password'])}</span><strong>{text(property_data['wifi_password'])}</strong></section>
    <section class="row"><strong>{text(labels['check_in'])}</strong>{text(property_data['check_in'])}</section>
    <section class="row"><strong>{text(labels['check_out'])}</strong>{text(property_data['check_out'])}</section>
    <section class="row"><strong>{text(labels['house_rules'])}</strong>{text(quiet_hours)}</section>
    <section class="emergency"><strong>{text(labels['emergency_information'])}: {text(emergency['emergency_number'])}</strong><br>{text(emergency['property_manager'])}</section>
  </main>
</body>
</html>"""
