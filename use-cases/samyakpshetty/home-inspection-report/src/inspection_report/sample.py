"""A fictional property, inspector and inspection.

Invented, as the brief expects — no real address, no real person, and no third party's
photographs. The images are drawn here rather than sourced, so the repository carries real
image bytes that are unambiguously ours, the offline demo needs nothing downloaded, and the
tests operate on genuine pictures instead of placeholder byte strings.

The findings are written the way an inspector actually types them: clipped, abbreviated, and
unreadable to a buyer. That is the input the report builder exists to transform, and two of
them are chosen because they provoke exactly the certification language the rail refuses.
"""

from __future__ import annotations

import datetime as dt
import io

from PIL import Image, ImageDraw

from inspection_report.domain.models import (
    Finding,
    Inspection,
    Inspector,
    Photo,
    Property,
)

# Muted, distinguishable, and dark enough for white label text.
_TONES = {
    "roof": (96, 108, 122),
    "electrical": (120, 96, 74),
    "plumbing": (74, 106, 120),
    "hvac": (104, 100, 116),
    "structure": (110, 104, 92),
    "exterior": (88, 112, 96),
}


def photo_bytes(system_key: str, label: str, *, size: tuple[int, int] = (720, 480)) -> bytes:
    """Draw a labelled stand-in photograph. Deterministic: same label, same bytes."""
    base = _TONES.get(system_key, (100, 100, 100))
    image = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(image)

    # A little structure so the image reads as a photograph of something rather than a
    # flat swatch, and so the PDF and DOCX renderings are visibly non-trivial.
    for i in range(0, size[0], 48):
        shade = tuple(min(255, c + (12 if (i // 48) % 2 else -8)) for c in base)
        draw.rectangle([i, 0, i + 24, size[1]], fill=shade)
    draw.rectangle([24, 24, size[0] - 24, size[1] - 24], outline=(245, 245, 245), width=3)
    draw.rectangle([24, size[1] - 96, size[0] - 24, size[1] - 24], fill=(20, 20, 20))
    draw.text((44, size[1] - 74), label[:58], fill=(255, 255, 255))
    draw.text((44, 44), system_key.upper(), fill=(255, 255, 255))

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _photo(system_key: str, label: str, caption: str) -> Photo:
    data = photo_bytes(system_key, label)
    import hashlib

    return Photo(
        sha256=hashlib.sha256(data).hexdigest(),
        filename=f"{system_key}-{label.lower().replace(' ', '-')[:24]}.png",
        content_type="image/png",
        size_bytes=len(data),
        width=720,
        height=480,
        caption=caption,
    )


def sample_photo_data() -> dict[str, bytes]:
    """Every sample photograph, keyed by filename, so the demo can upload real bytes."""
    out: dict[str, bytes] = {}
    for finding in sample_inspection().findings:
        for photo in finding.photos:
            label = photo.filename.rsplit(".", 1)[0].split("-", 1)[-1].replace("-", " ")
            out[photo.filename] = photo_bytes(finding.system_key, label)
    return out


def sample_inspection() -> Inspection:
    """One property, six systems, eight findings, eight photographs."""
    return Inspection(
        property=Property(
            address_line="14 Alder Lane",
            city="Fairhaven",
            postcode="FH8 2QR",
            year_built=1974,
            property_type="Detached two-storey",
        ),
        inspector=Inspector(
            name="Dana Whitfield",
            licence_number="QX-4471",
            firm_name="Alderwood Property Services",
        ),
        inspected_on=dt.date(2026, 8, 12),
        findings=[
            Finding(
                system_key="roof",
                severity_key="repair",
                location="North chimney",
                observation="S flashing gap ~2in @ chimney, staining on ceiling below",
                recommendation="Evaluation by a licensed roofing contractor.",
                photos=[
                    _photo("roof", "chimney flashing", "Gap in the flashing at the north chimney"),
                ],
            ),
            Finding(
                system_key="roof",
                severity_key="maintenance",
                location="Gutters, rear elevation",
                observation="gutters full, downpipe discharging at foundation",
                recommendation="Clear the gutters and extend the downpipe away from the wall.",
                photos=[_photo("roof", "rear gutter", "Debris in the rear gutter run")],
            ),
            Finding(
                system_key="electrical",
                severity_key="safety_concern",
                location="Kitchen",
                observation="GFCI kitchen - no trip on test button",
                recommendation="Evaluation by a licensed electrician before closing.",
                photos=[_photo("electrical", "kitchen gfci", "The kitchen GFCI receptacle")],
            ),
            Finding(
                system_key="electrical",
                severity_key="monitor",
                location="Main panel",
                observation="panel 1974 orig, no obvious defect, dbl tap on 2 breakers",
                recommendation="Evaluation of the double-tapped breakers by an electrician.",
                photos=[_photo("electrical", "main panel", "The main distribution panel")],
            ),
            Finding(
                system_key="plumbing",
                severity_key="repair",
                location="Master bathroom",
                observation="drip @ supply under sink, cabinet base swollen",
                recommendation="Repair by a licensed plumber.",
                photos=[_photo("plumbing", "under sink", "Supply connection under the sink")],
            ),
            Finding(
                system_key="hvac",
                severity_key="maintenance",
                location="Furnace, basement",
                observation="filter heavily loaded, unit 2011, ran on call",
                recommendation="Replace the filter and service the unit.",
                photos=[_photo("hvac", "furnace filter", "The furnace filter housing")],
            ),
            Finding(
                system_key="structure",
                severity_key="monitor",
                location="Basement, west wall",
                observation="hairline settling crack ~3ft vertical, no displacement",
                recommendation="Monitor the crack and record any change in width.",
                photos=[_photo("structure", "basement crack", "Vertical crack in the west wall")],
            ),
            Finding(
                system_key="exterior",
                severity_key="repair",
                location="Front walkway",
                observation="slab lifted ~1in at joint, trip hazard",
                recommendation="Evaluation and levelling by a concrete contractor.",
                photos=[_photo("exterior", "front walkway", "Lifted slab on the front walkway")],
            ),
        ],
    )
