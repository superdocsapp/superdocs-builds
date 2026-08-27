"""Unit tests for the deterministic renderer."""

from __future__ import annotations

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    ReleaseEntry,
)
from changelog_maintainer.renderer import render_entry, render_full_changelog


def _entry(version: str, date: str, **sections: list[dict]) -> ReleaseEntry:
    payload = {"version": version, "date": date, "sections": sections}
    return ReleaseEntry.from_payload(payload)


def test_renderer_is_deterministic_across_calls():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello"}],
        Fixed=[{"text": "Bug"}],
    )
    a = render_entry(entry, style, doc)
    b = render_entry(entry, style, doc)
    assert a == b


def test_renderer_keeps_section_canonical_order():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Fixed=[{"text": "Bug"}],
        Breaking=[{"text": "Boom"}],
        Added=[{"text": "Hello"}],
    )
    rendered = render_entry(entry, style, doc)
    # Added comes before Fixed, which comes before Breaking.
    assert rendered.index("### Added") < rendered.index("### Fixed")
    assert rendered.index("### Fixed") < rendered.index("### Breaking")


def test_renderer_omits_empty_sections():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello"}],
    )
    rendered = render_entry(entry, style, doc)
    assert "### Added" in rendered
    assert "### Fixed" not in rendered
    assert "### Breaking" not in rendered


def test_renderer_emits_comparison_link():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(
        title="Changelog", style=style, owner="me", repo="cool",
        entries=(_entry("1.0.0", "2026-01-01", Added=[{"text": "x"}]),),
    )
    entry = _entry("1.1.0", "2026-02-01", Added=[{"text": "y"}])
    rendered = render_entry(entry, style, doc)
    assert "Compare 1.0.0...1.1.0" in rendered
    assert "https://github.com/me/cool/compare/1.0.0...1.1.0" in rendered


def test_renderer_handles_links_within_items():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello", "link": "https://example.com/hello"}],
    )
    rendered = render_entry(entry, style, doc)
    assert "[Hello](https://example.com/hello)" in rendered


def test_renderer_renders_contributors_footer():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello"}],
    )
    rendered = render_entry(entry, style, doc, ) if False else None
    # Build contributors in.
    from dataclasses import replace

    entry = replace(entry, contributors=("octocat", "monalisa"))
    rendered = render_entry(entry, style, doc)
    assert "Thanks to @octocat, @monalisa" in rendered


def test_full_changelog_renders_title_and_entries():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(
        title="My Changelog",
        style=style,
        entries=(
            _entry("1.1.0", "2026-02-01", Added=[{"text": "B"}]),
            _entry("1.0.0", "2026-01-01", Added=[{"text": "A"}]),
        ),
    )
    rendered = render_full_changelog(doc)
    assert rendered.startswith("# My Changelog\n")
    # 1.1.0 is the newer release, must appear first.
    assert rendered.index("[1.1.0]") < rendered.index("[1.0.0]")


def test_emoji_policy_none_does_not_emit_unicode():
    style = HouseStyle(emoji_policy="none")
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello"}],
    )
    rendered = render_entry(entry, style, doc)
    # No emoji characters should appear.
    for ch in rendered:
        assert ord(ch) < 0x2700, f"unexpected emoji in {rendered!r}"


def test_emoji_policy_section_prefix_adds_emoji():
    style = HouseStyle(emoji_policy="section_prefix")
    doc = ChangelogDocument(title="Changelog", style=style)
    entry = _entry(
        "1.0.0",
        "2026-01-01",
        Added=[{"text": "Hello"}],
    )
    rendered = render_entry(entry, style, doc)
    assert "✨" in rendered
    assert "### ✨ Added" in rendered
