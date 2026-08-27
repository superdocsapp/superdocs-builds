"""Unit tests for the data model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    Link,
    ReleaseEntry,
    ReleaseSection,
    SectionItem,
)


def test_house_style_defaults_match_keep_a_changelog():
    a = HouseStyle()
    b = HouseStyle.keep_a_changelog()
    assert a.to_dict() == b.to_dict()


def test_house_style_validates_heading_level():
    with pytest.raises(ValueError):
        HouseStyle(heading_level=0)
    with pytest.raises(ValueError):
        HouseStyle(section_heading_level=7)


def test_house_style_rejects_bad_emoji_policy():
    with pytest.raises(ValueError):
        HouseStyle(emoji_policy="sparkles")


def test_house_style_rejects_duplicate_section_order():
    with pytest.raises(ValueError):
        HouseStyle(section_order=(ReleaseSection.ADDED, ReleaseSection.ADDED))


def test_section_item_validates_text():
    with pytest.raises(ValueError):
        SectionItem(text="")
    with pytest.raises(ValueError):
        SectionItem(text="ok", link="")


def test_link_validates_url():
    with pytest.raises(ValueError):
        Link(label="x", url="ftp://example.com")


def test_release_entry_rejects_invalid_semver():
    with pytest.raises(ValueError):
        ReleaseEntry(version="1.0", date="2026-01-01", sections={})


def test_release_entry_rejects_invalid_date():
    with pytest.raises(ValueError):
        ReleaseEntry(version="1.0.0", date="Jan 1 2026", sections={})


def test_release_entry_rejects_empty_sections():
    with pytest.raises(ValueError):
        ReleaseEntry(
            version="1.0.0",
            date="2026-01-01",
            sections={ReleaseSection.ADDED: ()},
        )


def test_release_entry_from_payload_round_trip():
    payload = {
        "version": "1.2.3",
        "date": "2026-03-04",
        "summary": "Hello",
        "sections": {
            "Added": [{"text": "X", "link": "https://example.com"}],
            "Fixed": [{"text": "Y"}],
        },
        "contributors": ["octocat"],
        "links": [{"label": "blog", "url": "https://example.com/blog"}],
    }
    entry = ReleaseEntry.from_payload(payload)
    assert entry.version == "1.2.3"
    assert entry.has_breaking() is False
    assert ReleaseSection.ADDED in entry.sections
    out = entry.to_payload()
    # Round-trip through JSON to make sure the dict is JSON-serializable.
    json.dumps(out)
    # The sections dict values must be lists of dicts after serialization.
    assert isinstance(out["sections"]["Added"], list)


def test_release_entry_from_payload_rejects_unknown_section():
    with pytest.raises(ValueError):
        ReleaseEntry.from_payload(
            {
                "version": "1.0.0",
                "date": "2026-01-01",
                "sections": {"Surprise": [{"text": "x"}]},
            }
        )


def test_changelog_document_with_new_entry_inserts_at_top():
    doc = ChangelogDocument(
        title="Changelog",
        style=HouseStyle.keep_a_changelog(),
        entries=(
            ReleaseEntry.from_payload(
                {"version": "1.0.0", "date": "2026-01-01", "sections": {"Added": [{"text": "x"}]}}
            ),
        ),
    )
    new = ReleaseEntry.from_payload(
        {"version": "1.1.0", "date": "2026-02-01", "sections": {"Added": [{"text": "y"}]}}
    )
    doc2 = doc.with_new_entry(new)
    assert [e.version for e in doc2.entries] == ["1.1.0", "1.0.0"]


def test_changelog_document_refuses_duplicate_version():
    doc = ChangelogDocument(
        title="Changelog",
        style=HouseStyle.keep_a_changelog(),
        entries=(
            ReleaseEntry.from_payload(
                {"version": "1.0.0", "date": "2026-01-01", "sections": {"Added": [{"text": "x"}]}}
            ),
        ),
    )
    dup = ReleaseEntry.from_payload(
        {"version": "1.0.0", "date": "2026-02-01", "sections": {"Added": [{"text": "y"}]}}
    )
    with pytest.raises(ValueError):
        doc.with_new_entry(dup)


def test_changelog_document_serialization(tmp_path: Path):
    doc = ChangelogDocument(
        title="Changelog",
        style=HouseStyle.keep_a_changelog(),
        owner="me",
        repo="cool",
    )
    path = tmp_path / "state.json"
    doc.save(path)
    again = ChangelogDocument.load(path)
    assert again.title == doc.title
    assert again.style.to_dict() == doc.style.to_dict()
    assert again.entries == doc.entries
