"""Captioned image embed into speaking-script markdown — no SuperDocs."""

from __future__ import annotations

from pathlib import Path

from generator.imagegen import PRESENTER_VISUAL_MARKER
from generator.narrative import (
    SectionImageEmbed,
    embed_images_into_markdown,
    parse_script_sections,
    write_image_bearing_script,
    write_presenter_chart_png,
)


def _script() -> str:
    return "\n".join(
        [
            "# ClarityDocs — Pitch Speaking Script",
            "",
            f"**{PRESENTER_VISUAL_MARKER.split('(')[0].strip()}**",
            "",
            "**Speaking script — not a slide deck.**",
            "",
            "## Slide-equivalent 6 — Proof / Case Study",
            "",
            "*Talking point:* HarborPay staged twelve findings in hours, not weeks.",
            "",
            "*Speaker notes:* Rejected four over-claims; committed eight with citations.",
            "",
            "## Slide-equivalent 8 — ROI / Business Case",
            "",
            "*Talking point:* The labour case is days of archaeology versus one export.",
            "",
            "*Speaker notes:* No figure in this section on this pass.",
            "",
        ]
    )


def test_embed_lands_in_named_section_after_talking_point() -> None:
    embed = SectionImageEmbed(
        section_number=6,
        caption="HarborPay staged 12 findings; 4 rejected, 8 committed",
        src="presenter-visuals/fintech-section-6.png",
    )
    out = embed_images_into_markdown(_script(), [embed])
    bodies = parse_script_sections(out)
    assert "presenter-visuals/fintech-section-6.png" in bodies[6]
    assert PRESENTER_VISUAL_MARKER.lower() in bodies[6].lower()
    assert "presenter-visuals/fintech-section-6.png" not in bodies[8]
    six = bodies[6].lower()
    assert six.index("talking point") < six.index("presenter-visuals/")
    assert six.index("presenter-visuals/") < six.index("speaker notes")


def test_embed_is_idempotent_for_the_same_src() -> None:
    embed = SectionImageEmbed(
        section_number=6,
        caption="HarborPay staged counts",
        src="presenter-visuals/fintech-section-6.png",
    )
    once = embed_images_into_markdown(_script(), [embed])
    twice = embed_images_into_markdown(once, [embed])
    assert once.count("presenter-visuals/fintech-section-6.png") == twice.count(
        "presenter-visuals/fintech-section-6.png"
    )


def test_write_image_bearing_script_passes_format_guard(tmp_path: Path) -> None:
    source = tmp_path / "src" / "pitch-script-fintech-claritydocs.md"
    source.parent.mkdir()
    source.write_text(_script(), encoding="utf-8")
    dest = tmp_path / "export"
    png = write_presenter_chart_png(dest / "presenter-visuals" / "fintech-section-6.png")
    assert png.is_file() and png.stat().st_size > 32
    paths = write_image_bearing_script(
        source,
        dest,
        [
            SectionImageEmbed(
                section_number=6,
                caption="HarborPay staged 12 / rejected 4 / committed 8",
                src="presenter-visuals/fintech-section-6.png",
            )
        ],
    )
    text = paths["markdown"].read_text(encoding="utf-8")
    assert "Speaking script — not a slide deck." in text
    assert "![Presenter visual" in text or PRESENTER_VISUAL_MARKER in text
