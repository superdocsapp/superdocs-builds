"""Render a grounded manuscript skeleton as uploadable semantic HTML."""

from __future__ import annotations

from html import escape
from typing import Mapping

from .models import ManuscriptSkeleton, SectionStatus


def _render_text(value: str) -> str:
    return escape(value).replace("\n", "<br>")


def render_manuscript_html(
    skeleton: ManuscriptSkeleton,
    generated_sections: Mapping[str, str] | None = None,
) -> str:
    """Render content without adding scientific claims or journal requirements."""

    generated_sections = generated_sections or {}
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head><meta charset=\"utf-8\"><title>Manuscript Skeleton</title></head>",
        "<body>",
        "<article>",
        "<h1>Manuscript Skeleton</h1>",
    ]
    for section in skeleton.sections:
        parts.append(
            f'<section data-paper-scaffolder-section="{escape(section.section_id)}">'
        )
        parts.append(f"<h2>{escape(section.title)}</h2>")
        content = generated_sections.get(section.section_id, section.content)
        if content:
            parts.append(f"<p>{_render_text(content)}</p>")
        elif section.status is SectionStatus.INSUFFICIENT_INFORMATION:
            parts.append(
                '<p><em data-paper-scaffolder-status="insufficient_information">'
                f"[{_render_text(section.reason)} This section has not been generated.]"
                "</em></p>"
            )
        parts.append("</section>")
    parts.extend(["</article>", "</body>", "</html>"])
    return "\n".join(parts)


def manuscript_filename(skeleton: ManuscriptSkeleton) -> str:
    return f"paper-scaffold-{skeleton.manuscript_id}.html"
