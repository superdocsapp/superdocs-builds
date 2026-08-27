"""Unit tests for identity verification."""

from __future__ import annotations

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    ReleaseEntry,
)
from changelog_maintainer.verification import (
    canonical_hash,
    verify_entries,
    verify_html_anchors,
)


def _entry(version: str, date: str, text: str) -> ReleaseEntry:
    return ReleaseEntry.from_payload(
        {"version": version, "date": date, "sections": {"Added": [{"text": text}]}}
    )


def test_canonical_hash_is_stable_for_same_inputs():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="C", style=style)
    e1 = _entry("1.0.0", "2026-01-01", "Hello")
    h1 = canonical_hash((e1,), doc)
    h2 = canonical_hash((e1,), doc)
    assert h1 == h2


def test_canonical_hash_changes_when_entry_changes():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(title="C", style=style)
    e1 = _entry("1.0.0", "2026-01-01", "Hello")
    e2 = _entry("1.0.0", "2026-01-01", "Hello world")
    assert canonical_hash((e1,), doc) != canonical_hash((e2,), doc)


def test_verify_entries_passes_when_priors_unchanged():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(
        title="C",
        style=style,
        entries=(_entry("1.0.0", "2026-01-01", "A"),),
    )
    doc2 = doc.with_new_entry(_entry("1.1.0", "2026-02-01", "B"))
    result = verify_entries(doc.entries, doc2.entries, doc2)
    assert result.passed


def test_verify_entries_fails_when_prior_is_mutated():
    style = HouseStyle.keep_a_changelog()
    doc = ChangelogDocument(
        title="C",
        style=style,
        entries=(_entry("1.0.0", "2026-01-01", "A"),),
    )
    # Simulate an unauthorized mutation of the prior entry.
    tampered = doc.without_last()
    tampered = ChangelogDocument(
        title=tampered.title,
        style=tampered.style,
        entries=(_entry("1.0.0", "2026-01-01", "A TAMPERED"),),
    )
    # Now suppose someone "appends" a new release on top of the tampered doc.
    fake_after = tampered.with_new_entry(_entry("1.1.0", "2026-02-01", "B"))
    result = verify_entries(doc.entries, fake_after.entries, doc)
    assert not result.passed


def test_verify_html_anchors_detects_missing_heading():
    before = "<h2>[1.0.0] - 2026-01-01</h2><p>old</p>"
    after = "<h2>[1.1.0] - 2026-02-01</h2><p>new</p>"
    result = verify_html_anchors(before, after)
    assert not result.passed
    assert "[1.0.0] - 2026-01-01" in result.missing_headings


def test_verify_html_anchors_passes_when_prior_intact():
    before = "<h2>[1.0.0] - 2026-01-01</h2><p>old</p>"
    after = (
        "<h2>[1.1.0] - 2026-02-01</h2>"
        "<h2>[1.0.0] - 2026-01-01</h2><p>old</p>"
    )
    result = verify_html_anchors(before, after)
    assert result.passed


def test_verify_html_anchors_detects_out_of_order():
    before = (
        "<h2>[1.0.0] - 2026-01-01</h2>"
        "<h2>[0.9.0] - 2025-12-01</h2>"
    )
    # After: 0.9.0 was moved above 1.0.0.
    after = (
        "<h2>[0.9.0] - 2025-12-01</h2>"
        "<h2>[1.0.0] - 2026-01-01</h2>"
    )
    result = verify_html_anchors(before, after)
    assert not result.passed
    assert result.out_of_order
