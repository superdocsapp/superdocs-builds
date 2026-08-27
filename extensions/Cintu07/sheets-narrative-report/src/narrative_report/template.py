"""The firm template.

Kept as data, an HTML shell plus a stylesheet, rather than as code that builds
markup, so changing the house style is a content edit and not a rewrite. A firm
swapping in its own letterhead should not need to touch Python.

The shell is deliberately conservative: exports have to survive a round trip
into .docx, where exotic layout degrades badly. Simple block structure and
inline-safe CSS render predictably in Word, Google Docs and PDF alike.
"""

from __future__ import annotations

import html as html_lib
import pathlib
from collections.abc import Iterable

from .models import Section

TEMPLATE_DIR = pathlib.Path(__file__).parent / "assets"
DEFAULT_TEMPLATE = TEMPLATE_DIR / "firm_template.html"

PLACEHOLDER_TITLE = "{{title}}"
PLACEHOLDER_META = "{{meta}}"
PLACEHOLDER_BODY = "{{body}}"


def load_template(path: pathlib.Path | str | None = None) -> str:
    """Read the firm shell, falling back to the packaged default."""
    chosen = pathlib.Path(path) if path else DEFAULT_TEMPLATE
    if not chosen.exists():
        raise FileNotFoundError(
            f"firm template not found at {chosen}. Set NARRATIVE_TEMPLATE to a valid "
            "HTML file containing {{title}}, {{meta}} and {{body}} placeholders."
        )
    return chosen.read_text(encoding="utf-8")


def assemble_document(
    *,
    title: str,
    source_range: str,
    sections: Iterable[Section],
    chart_url: str | None = None,
    template_path: pathlib.Path | str | None = None,
) -> str:
    """Fill the firm shell with the approved sections.

    Section bodies are inserted already rendered, substitution and verification
    happened upstream, so this function never sees a token and never sees a
    number it could get wrong.
    """
    from .chart import chart_html

    shell = load_template(template_path)
    blocks: list[str] = []
    for index, section in enumerate(sections):
        blocks.append(f'<h2 class="report-heading">{html_lib.escape(section.heading)}</h2>')
        blocks.append(f'<div data-section-id="{html_lib.escape(section.id)}">')
        blocks.append(section.rendered or "")
        blocks.append("</div>")
        if index == 0 and chart_url:
            blocks.append(chart_html(chart_url, f"Chart of {source_range}"))

    return (
        shell.replace(PLACEHOLDER_TITLE, html_lib.escape(title))
        .replace(PLACEHOLDER_META, html_lib.escape(f"Source: {source_range}"))
        .replace(PLACEHOLDER_BODY, "".join(blocks))
    )
