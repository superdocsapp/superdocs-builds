"""Deterministic Markdown renderer for ReleaseEntry under a HouseStyle.

Given (entry, style, document), render_entry produces the EXACT byte sequence
for that release's section. No timestamps, no randomness, no environment
lookups — same inputs always produce the same bytes.

This is what makes identity verification possible: the renderer is a pure
function, and re-rendering an old entry always reproduces the original bytes.
"""

from __future__ import annotations

import re
from typing import Iterable

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    Link,
    ReleaseEntry,
    ReleaseSection,
    SectionItem,
)


# ---------------------------------------------------------------------------
# Section emoji table (used only when emoji_policy allows it).
# ---------------------------------------------------------------------------

_SECTION_EMOJI: dict[ReleaseSection, str] = {
    ReleaseSection.BREAKING: "⚠️ ",  # ⚠️
    ReleaseSection.ADDED: "✨ ",  # ✨
    ReleaseSection.CHANGED: "🔄 ",  # 🔄
    ReleaseSection.DEPRECATED: "🚫 ",  # 🚫
    ReleaseSection.REMOVED: "🗑️ ",  # 🗑️
    ReleaseSection.FIXED: "🐛 ",  # 🐛
    ReleaseSection.SECURITY: "🔒 ",  # 🔒
}

_TITLE_EMOJI = "🎉 "  # 🎉


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_full_changelog(document: ChangelogDocument) -> str:
    """Render the entire changelog as Markdown, top entry first.

    The output starts with a single H1 title and concatenates each entry
    rendered by render_entry(). Deterministic.
    """
    parts: list[str] = [_render_h1(document.title)]
    for entry in document.entries:
        parts.append(render_entry(entry, document.style, document))
    return "\n".join(parts) + "\n"


def render_entry(
    entry: ReleaseEntry,
    style: HouseStyle,
    document: ChangelogDocument | None = None,
) -> str:
    """Render a single release entry as a Markdown block.

    The block ends with `style.trailing_blank_lines` blank lines so that
    successive entries are visually separated. Byte-identical for equal inputs.
    """
    blocks: list[str] = []

    # 1) Title (h{heading_level})
    title = style.title_format.format(version=entry.version, date=entry.date)
    if style.emoji_policy == "title_prefix":
        title = _TITLE_EMOJI + title
    blocks.append(_render_heading(style.heading_level, title))

    # 2) Optional summary (styled as clean subtitle blockquote)
    if entry.summary:
        blocks.append(f"> *{entry.summary.strip()}*")
        blocks.append("")

    # 3) Sections, in canonical order, skipping empty ones.
    for section in style.section_order:
        items = entry.sections.get(section)
        if not items:
            continue
        section_title = section.value
        if style.emoji_policy == "section_prefix":
            section_title = _SECTION_EMOJI[section] + section_title
        blocks.append(_render_heading(style.section_heading_level, section_title))
        blocks.extend(_render_items(items, style.bullet_marker))
        blocks.append("")

    # 4) Contributors footer (consistent format across releases).
    if entry.contributors:
        names = ", ".join(_normalize_contributor(c) for c in entry.contributors)
        blocks.append(f"Thanks to {names} for contributing to this release.")
        blocks.append("")

    # 5) Links footer: deduplicate comparison link and format cleanly.
    links = _build_links(entry, document, style)
    if links:
        rendered = " | ".join(_render_link(l) for l in links)
        blocks.append(rendered)
        blocks.append("")

    # Trim a trailing blank that the loop above always appends, then add the
    # exact number of blank lines configured. Output is stable.
    while blocks and blocks[-1] == "":
        blocks.pop()
    blocks.extend([""] * style.trailing_blank_lines)

    return "\n".join(blocks).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _render_h1(text: str) -> str:
    return f"# {text}\n"


def _render_heading(level: int, text: str) -> str:
    marker = "#" * level
    return f"{marker} {text}\n"


def _render_items(items: Iterable[SectionItem], bullet: str) -> list[str]:
    out: list[str] = []
    for item in items:
        if item.link:
            out.append(f"{bullet} {_render_inline_link(item.text, item.link)}")
        else:
            out.append(f"{bullet} {item.text}")
    return out


def _render_inline_link(text: str, url: str) -> str:
    return f"[{_escape_md(text)}]({url})"


def _render_link(link: Link) -> str:
    return f"[{_escape_md(link.label)}]({link.url})"


def _build_links(
    entry: ReleaseEntry,
    document: ChangelogDocument | None,
    style: HouseStyle,
) -> list[Link]:
    out: list[Link] = []
    has_explicit_compare = False
    cleaned_entry_links: list[Link] = []

    for l in entry.links:
        lbl_lower = l.label.strip().lower()
        if "compare" in lbl_lower or "diff" in lbl_lower or "/compare/" in l.url:
            has_explicit_compare = True
            clean_label = l.label
            if lbl_lower in ("compare", "diff", "comparison"):
                if "/compare/" in l.url:
                    comp_part = l.url.split("/compare/")[1].split("?")[0].split("#")[0]
                    clean_label = f"Compare {comp_part}"
                else:
                    clean_label = "Compare Changes"
            cleaned_entry_links.append(Link(label=clean_label, url=l.url))
        elif lbl_lower in ("release", "release notes", "notes"):
            cleaned_entry_links.append(Link(label="Release Notes", url=l.url))
        else:
            cleaned_entry_links.append(l)

    if not has_explicit_compare and style.include_comparison_link and document is not None:
        prev = _previous_version(entry, document)
        if prev is not None:
            v_prefix = "v" if any("/v" in l.url for l in entry.links) else ""
            prev_tag = f"{v_prefix}{prev}" if not prev.startswith("v") and v_prefix else prev
            ver_tag = f"{v_prefix}{entry.version}" if not entry.version.startswith("v") and v_prefix else entry.version
            url = style.comparison_link_format.format(
                owner=document.owner,
                repo=document.repo,
                previous=prev_tag,
                version=ver_tag,
            )
            out.append(Link(label=f"Compare {prev_tag}...{ver_tag}", url=url))

    out.extend(cleaned_entry_links)
    return out


def _previous_version(entry: ReleaseEntry, document: ChangelogDocument) -> str | None:
    """Find the release immediately older than `entry.version` in the doc."""
    versions = [e.version for e in document.entries]
    if entry.version in versions:
        idx = versions.index(entry.version)
        if idx + 1 < len(versions):
            return versions[idx + 1]
        return None
    # Entry not yet inserted (e.g. previewing candidate entry).
    for existing in document.entries:
        if (existing.date, existing.version) < (entry.date, entry.version):
            return existing.version
    if versions:
        return versions[0]
    return None


def _normalize_contributor(name: str) -> str:
    # Strip @ prefix and surrounding whitespace; GitHub handles are stable.
    n = name.strip()
    if n.startswith("@"):
        n = n[1:]
    if not n:
        raise ValueError("Contributor name must be non-empty")
    if not re.match(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$", n):
        # Not a GitHub handle — render the literal as-is, but quoted.
        return f"`{name.strip()}`"
    return f"@{n}"


def _escape_md(text: str) -> str:
    # Minimal escaping so contributor names with parens don't break the link.
    return text.replace("[", "\\[").replace("]", "\\]")


__all__ = ["render_entry", "render_full_changelog"]
