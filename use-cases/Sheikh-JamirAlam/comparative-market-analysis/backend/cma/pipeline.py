from datetime import date
import json
from pathlib import Path

from .models import Branding, Property
from .pricing import estimate_price_range
from .superdocs_client import (
    export_document,
    list_user_templates,
    send_chat_instruction,
    upload_user_template,
)


def generate_cma_from_saved_template(
    subject: Property,
    comps: list[Property],
    branding: Branding,
    out_path: str | Path,
    *,
    template_path: str | Path,
    template_name: str = "cma_saved_template.html",
    export_format: str = "pdf",
    api_key: str | None = None,
) -> Path:
    templates = list_user_templates(api_key=api_key)
    if not any(template.get("name") == template_name for template in templates):
        upload_user_template(template_path, api_key=api_key)

    price_range = estimate_price_range(subject, comps)
    placeholder_values = {
        "[AGENT NAME]": branding.agent_name,
        "[BROKERAGE NAME]": branding.brokerage,
        "[AGENT PHONE]": branding.phone,
        "[AGENT EMAIL]": branding.email,
        "[SUBJECT PROPERTY ADDRESS]": subject.address,
        "[SUBJECT CITY]": subject.city,
        "[SUBJECT STATE]": subject.state,
        "[SUBJECT BEDS]": subject.beds,
        "[SUBJECT BATHS]": subject.baths,
        "[SUBJECT SQFT]": subject.sqft,
        "[SUBJECT LOT SIZE]": subject.lot_size_sqft,
        "[SUBJECT YEAR BUILT]": subject.year_built,
        "[SUBJECT PHOTO URL]": subject.photo_url,
        "[DATE]": date.today().strftime("%B %d, %Y").replace(" 0", " "),
        "[PRICE_RANGE_PLACEHOLDER]": f"${price_range.low:,.0f} - ${price_range.high:,.0f}",
        "[PRICE_RANGE_BASIS_PLACEHOLDER]": price_range.rationale,
    }
    comparables = [
        {
            "address": comp.address,
            "city": comp.city,
            "state": comp.state,
            "sale_price": comp.sale_price or comp.list_price,
            "sqft": comp.sqft,
            "price_per_sqft": round((comp.sale_price or comp.list_price) / comp.sqft, 2),
            "beds": comp.beds,
            "baths": comp.baths,
            "sale_date": comp.sale_date,
            "photo_url": comp.photo_url,
        }
        for comp in comps
        if comp.sqft > 0
    ]
    session_id = str(__import__("uuid").uuid4())
    send_chat_instruction(
        session_id,
        "Create a new CMA using my saved " + template_name + " template. Replace every exact placeholder using this mapping::\n" +
        json.dumps(placeholder_values, indent=2) + "\n"
        "Replace placeholders in visible text and in HTML attributes, especially image src and alt attributes. "
        "Do not leave any bracketed placeholders anywhere in the final document. "
        "Replace [COMPARABLES_TABLE_PLACEHOLDER] with a properly formatted table including each comparable's photo URL, address, sale price, square feet, price per square foot, beds/baths, and sale date. Replace the price-range placeholders with the supplied range and rationale. Use this comparable data to build the table, without inventing facts:\n" +
        json.dumps(comparables, indent=2) +
        "\nPreserve the template's branding and layout.",
        api_key=api_key,
    )
    exported = export_document(session_id, export_format, api_key=api_key)
    destination = Path(out_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(exported)
    return destination


def property_from_dict(data: dict[str, object]) -> Property:
    return Property(**data)


def branding_from_dict(data: dict[str, object]) -> Branding:
    return Branding(**data)
