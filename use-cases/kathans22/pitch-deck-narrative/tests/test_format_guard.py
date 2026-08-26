"""format_guard: structural checks that exports are speaking scripts, not decks."""

from __future__ import annotations

from pathlib import Path

import pytest

from generator.format_guard import (
    FormatGuardError,
    SPEAKING_SCRIPT_DISCLAIMER,
    assert_not_deck,
)


def _write_script(path: Path, *, title: str, include_disclaimer: bool = True) -> Path:
    lines = [f"# {title}", ""]
    if include_disclaimer:
        lines.append(f"**{SPEAKING_SCRIPT_DISCLAIMER}**")
        lines.append("")
    lines.extend(
        [
            "Vertical: Legal. Speaking sections only.",
            "",
            "## Slide-equivalent 1 — Opening / Hook",
            "",
            "**Talking point:** Hello.",
            "",
            "**Speaker notes:** Notes here.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_guard_passes_legal_style_speaking_script(tmp_path: Path) -> None:
    path = _write_script(
        tmp_path / "pitch-script-legal-claritydocs.md",
        title="ClarityDocs — Pitch Speaking Script",
    )
    assert_not_deck(path, "ClarityDocs — Pitch Speaking Script", export_format="markdown")


def test_guard_rejects_deliberately_mistitled_document(tmp_path: Path) -> None:
    """A deck-shaped title must fail with format_guard.title named in the error."""
    path = _write_script(
        tmp_path / "pitch-script-legal-claritydocs.md",
        title="ClarityDocs Investor Pitch Deck",
    )
    with pytest.raises(FormatGuardError, match=r"format_guard\.title") as exc_info:
        assert_not_deck(
            path,
            "ClarityDocs Investor Pitch Deck",
            export_format="markdown",
        )
    assert "deck" in str(exc_info.value).lower()


def test_guard_rejects_deck_filename(tmp_path: Path) -> None:
    path = _write_script(
        tmp_path / "pitch-deck-legal-claritydocs.md",
        title="ClarityDocs — Pitch Speaking Script",
    )
    with pytest.raises(FormatGuardError, match=r"format_guard\.filename"):
        assert_not_deck(
            path,
            "ClarityDocs — Pitch Speaking Script",
            export_format="markdown",
        )


def test_guard_rejects_missing_disclaimer(tmp_path: Path) -> None:
    path = _write_script(
        tmp_path / "pitch-script-legal-claritydocs.md",
        title="ClarityDocs — Pitch Speaking Script",
        include_disclaimer=False,
    )
    with pytest.raises(FormatGuardError, match=r"format_guard\.disclaimer"):
        assert_not_deck(
            path,
            "ClarityDocs — Pitch Speaking Script",
            export_format="markdown",
        )


def test_guard_rejects_pptx_export_path() -> None:
    from generator.format_guard import assert_document_export_path

    with pytest.raises(FormatGuardError, match=r"format_guard\.export_path"):
        assert_document_export_path("pptx")


def test_guard_still_passes_with_image_bearing_export(tmp_path: Path) -> None:
    """An image in a section must not make the export look like a slide deck."""
    from generator.imagegen import PRESENTER_VISUAL_MARKER
    from generator.narrative import parse_script_sections

    lines = [
        "# ClarityDocs — Pitch Speaking Script",
        "",
        f"**{SPEAKING_SCRIPT_DISCLAIMER}**",
        "",
        "Vertical: Fintech. Speaking sections only — not a slide canvas.",
        "",
        "## Slide-equivalent 6 — Proof / Case Study",
        "",
        "*Talking point:* HarborPay staged twelve findings in hours, not weeks.",
        "",
        f"![{PRESENTER_VISUAL_MARKER}: HarborPay staged vs rejected vs committed](presenter-visuals/fintech-section-6.png)",
        "",
        f"*{PRESENTER_VISUAL_MARKER}: HarborPay staged 12, rejected 4, committed 8.*",
        "",
        "*Speaker notes:* The visual is a presenter cue, not a slide.",
        "",
    ]
    path = tmp_path / "pitch-script-fintech-claritydocs.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    assert_not_deck(
        path,
        "ClarityDocs — Pitch Speaking Script",
        export_format="markdown",
    )
    body = parse_script_sections(path.read_text(encoding="utf-8"))[6]
    assert "presenter-visuals/fintech-section-6.png" in body
    assert PRESENTER_VISUAL_MARKER.lower() in body.lower()


def test_committed_fintech_image_demo_still_passes_guard() -> None:
    from generator.manifest import project_root

    path = project_root() / "evidence" / "image-demo" / "pitch-script-fintech-claritydocs.md"
    assert path.is_file(), "image-demo export missing — Prompt 17 embed did not land"
    assert_not_deck(
        path,
        "ClarityDocs — Pitch Speaking Script",
        export_format="markdown",
    )
