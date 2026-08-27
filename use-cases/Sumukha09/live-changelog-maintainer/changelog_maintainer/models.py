"""Pure-Python dataclasses for the Living Changelog Maintainer.

Persistence: JSON files on disk. No databases, no ORMs.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Iterable


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<pre>[0-9A-Za-z.\-]+))?"
    r"(?:\+(?P<build>[0-9A-Za-z.\-]+))?$"
)


def _validate_semver(version: str) -> str:
    """Validate and normalize a semver version string. Reject anything else."""
    if not isinstance(version, str) or not _SEMVER_RE.match(version):
        raise ValueError(
            f"Invalid semver version: {version!r}. "
            "Expected MAJOR.MINOR.PATCH with optional pre-release/build."
        )
    return version


def _validate_iso_date(value: str) -> str:
    """Validate an ISO-8601 date (YYYY-MM-DD)."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid ISO date {value!r}: expected YYYY-MM-DD") from exc
    return value


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ReleaseSection(str, Enum):
    """Conventional release-note section categories, in canonical order."""

    BREAKING = "Breaking"
    ADDED = "Added"
    CHANGED = "Changed"
    DEPRECATED = "Deprecated"
    REMOVED = "Removed"
    FIXED = "Fixed"
    SECURITY = "Security"

    @classmethod
    def canonical_order(cls) -> tuple["ReleaseSection", ...]:
        return (
            cls.ADDED,
            cls.CHANGED,
            cls.FIXED,
            cls.BREAKING,
            cls.DEPRECATED,
            cls.REMOVED,
            cls.SECURITY,
        )


def _parse_section(key: str) -> ReleaseSection:
    """Parse section key with case-insensitivity."""
    key_norm = str(key).strip().lower()
    for section in ReleaseSection:
        if section.value.lower() == key_norm:
            return section
    valid = ", ".join(s.value for s in ReleaseSection)
    raise ValueError(f"Unknown section {key!r}. Valid sections: {valid}")


# ---------------------------------------------------------------------------
# Atomic value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SectionItem:
    """A single bullet inside a release section."""

    text: str
    link: str | None = None

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError("SectionItem.text must be non-empty")
        if self.link is not None and not self.link.strip():
            raise ValueError("SectionItem.link must be non-empty if provided")

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "link": self.link}


@dataclass(frozen=True, slots=True)
class Link:
    """A reference link (PR, issue, comparison URL)."""

    label: str
    url: str

    def __post_init__(self) -> None:
        if not self.label.strip():
            raise ValueError("Link.label must be non-empty")
        if not self.url.startswith(("http://", "https://")):
            raise ValueError(f"Link.url must be http(s); got {self.url!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "url": self.url}


# ---------------------------------------------------------------------------
# Release entry
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleaseEntry:
    """One release's contribution to the changelog.

    Sections that are empty are omitted from the rendered output, but their
    canonical ORDER is preserved by ReleaseSection.canonical_order().
    """

    version: str
    date: str  # YYYY-MM-DD
    sections: dict[ReleaseSection, tuple[SectionItem, ...]]
    contributors: tuple[str, ...] = ()
    links: tuple[Link, ...] = ()
    summary: str | None = None

    def __post_init__(self) -> None:
        _validate_semver(self.version)
        _validate_iso_date(self.date)
        # Make sure no section is given an empty tuple.
        empty = [s for s, items in self.sections.items() if not items]
        if empty:
            raise ValueError(
                f"ReleaseEntry {self.version}: sections with no items: "
                f"{[s.value for s in empty]}. Drop empty sections instead."
            )

    # ----- Convenience constructors -------------------------------------------------

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ReleaseEntry":
        """Build a ReleaseEntry from a JSON-ish dict (the release.json file)."""
        version = str(payload["version"])
        date_str = str(payload["date"])
        summary = payload.get("summary") or payload.get("title")

        sections: dict[ReleaseSection, tuple[SectionItem, ...]] = {}
        raw_sections = payload.get("sections", {})
        if not isinstance(raw_sections, dict):
            raise ValueError("'sections' must be a mapping")

        for key, items in raw_sections.items():
            section = _parse_section(key)
            if items is None:
                continue
            if not isinstance(items, (list, tuple)):
                raise ValueError(f"Section {key!r} must be a list")
            parsed_items: list[SectionItem] = []
            for it in items:
                if isinstance(it, str):
                    if it.strip():
                        parsed_items.append(SectionItem(text=it.strip()))
                elif isinstance(it, dict):
                    text = str(it.get("text", "")).strip()
                    if text:
                        parsed_items.append(SectionItem(text=text, link=it.get("link")))
            if parsed_items:
                sections[section] = tuple(parsed_items)

        contributors = tuple(payload.get("contributors", []) or ())
        raw_links = payload.get("links", []) or []
        links_list: list[Link] = []
        if isinstance(raw_links, dict):
            for label, url in raw_links.items():
                if url:
                    links_list.append(Link(label=str(label), url=str(url)))
        elif isinstance(raw_links, (list, tuple)):
            for l in raw_links:
                if isinstance(l, dict) and "label" in l and "url" in l:
                    links_list.append(Link(label=str(l["label"]), url=str(l["url"])))

        return cls(
            version=version,
            date=date_str,
            sections=sections,
            contributors=contributors,
            links=tuple(links_list),
            summary=summary,
        )

    # ----- Serialization ------------------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": self.version,
            "date": self.date,
            "sections": {
                section.value: [item.to_dict() for item in items]
                for section, items in self.sections.items()
            },
            "contributors": list(self.contributors),
            "links": [link.to_dict() for link in self.links],
        }
        if self.summary is not None:
            out["summary"] = self.summary
        return out

    # ----- Semantic helpers ---------------------------------------------------------

    def has_breaking(self) -> bool:
        return ReleaseSection.BREAKING in self.sections

    def section_count(self) -> int:
        return len(self.sections)

    def item_count(self) -> int:
        return sum(len(items) for items in self.sections.values())


# ---------------------------------------------------------------------------
# House style
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HouseStyle:
    """The visual / structural conventions of the changelog.

    Changing a value here would change how the entry is rendered. The renderer
    is deterministic given (entry, style); the same inputs always produce the
    same bytes.
    """

    heading_level: int = 2
    title_format: str = "[{version}] - {date}"
    bullet_marker: str = "-"  # Markdown bullet
    emoji_policy: str = "none"  # none | section_prefix | title_prefix
    section_heading_level: int = 3
    section_order: tuple[ReleaseSection, ...] = ReleaseSection.canonical_order()
    include_comparison_link: bool = True
    comparison_link_format: str = (
    "https://github.com/{owner}/{repo}/compare/{previous}...{version}"
)
    trailing_blank_lines: int = 1

    def __post_init__(self) -> None:
        if self.heading_level < 1 or self.heading_level > 6:
            raise ValueError("heading_level must be 1..6")
        if self.section_heading_level < 1 or self.section_heading_level > 6:
            raise ValueError("section_heading_level must be 1..6")
        if self.bullet_marker not in ("-", "*", "+"):
            raise ValueError("bullet_marker must be one of -, *, +")
        if self.emoji_policy not in ("none", "section_prefix", "title_prefix"):
            raise ValueError("emoji_policy must be none|section_prefix|title_prefix")
        if self.trailing_blank_lines < 0:
            raise ValueError("trailing_blank_lines must be >= 0")
        seen = set()
        for s in self.section_order:
            if s in seen:
                raise ValueError(f"section_order contains duplicate {s.value}")
            seen.add(s)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["section_order"] = [s.value for s in self.section_order]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "HouseStyle":
        raw = dict(d)
        order_raw = raw.get("section_order")
        if order_raw is not None:
            raw["section_order"] = tuple(ReleaseSection(s) for s in order_raw)
        return cls(**raw)

    # ----- Common presets -----------------------------------------------------------

    @classmethod
    def keep_a_changelog(cls) -> "HouseStyle":
        """The Keep a Changelog (https://keepachangelog.com) conventions."""
        return cls(
            heading_level=2,
            title_format="[{version}] - {date}",
            bullet_marker="-",
            emoji_policy="none",
            section_heading_level=3,
            section_order=ReleaseSection.canonical_order(),
        )


# ---------------------------------------------------------------------------
# Document state
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ChangelogDocument:
    """The standing changelog: its location, history, and house style."""

    title: str
    style: HouseStyle
    owner: str = "owner"
    repo: str = "repo"
    entries: tuple[ReleaseEntry, ...] = ()
    # SuperDocs durable document id (UUID), if any.
    superdocs_document_id: str | None = None
    # Local on-disk source of truth (Markdown mirror).
    source_path: str | None = None
    created_at: str = field(default_factory=lambda: date.today().isoformat())

    def __post_init__(self) -> None:
        if not self.title.strip():
            raise ValueError("ChangelogDocument.title must be non-empty")
        sorted_entries = tuple(
            sorted(
                self.entries,
                key=lambda e: (_date_key(e.date), _semver_key(e.version)),
                reverse=True,
            )
        )
        object.__setattr__(self, "entries", sorted_entries)

    # ----- History helpers ----------------------------------------------------------

    @property
    def latest_version(self) -> str | None:
        return self.entries[0].version if self.entries else None

    def has_version(self, version: str) -> bool:
        return any(e.version == version for e in self.entries)

    def with_new_entry(self, entry: ReleaseEntry) -> "ChangelogDocument":
        """Return a new ChangelogDocument with `entry` inserted at the top.

        Order is preserved (newest first). Duplicates are rejected loudly.
        """
        if self.has_version(entry.version):
            raise ValueError(
                f"Version {entry.version!r} already present in changelog. "
                "Refusing to overwrite an existing release."
            )
        # Sort entries: by date desc, then by semver desc as tiebreaker.
        new_entries = (entry,) + self.entries
        sorted_entries = tuple(
            sorted(
                new_entries,
                key=lambda e: (_date_key(e.date), _semver_key(e.version)),
                reverse=True,
            )
        )
        return replace(self, entries=sorted_entries)

    def without_last(self) -> "ChangelogDocument":
        """Test helper: drop the newest entry. Production code does not call this."""
        if not self.entries:
            raise ValueError("No entries to remove")
        return replace(self, entries=self.entries[1:])

    # ----- Persistence --------------------------------------------------------------

    def to_json(self) -> str:
        payload = {
            "title": self.title,
            "style": self.style.to_dict(),
            "owner": self.owner,
            "repo": self.repo,
            "superdocs_document_id": self.superdocs_document_id,
            "source_path": self.source_path,
            "created_at": self.created_at,
            "entries": [e.to_payload() for e in self.entries],
        }
        return json.dumps(payload, indent=2, sort_keys=False) + "\n"

    @classmethod
    def from_json(cls, raw: str) -> "ChangelogDocument":
        data = json.loads(raw)
        return cls.from_payload(data)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ChangelogDocument":
        entries = tuple(ReleaseEntry.from_payload(e) for e in payload.get("entries", []))
        style = HouseStyle.from_dict(payload["style"])
        return cls(
            title=payload["title"],
            style=style,
            owner=payload.get("owner", "owner"),
            repo=payload.get("repo", "repo"),
            entries=entries,
            superdocs_document_id=payload.get("superdocs_document_id"),
            source_path=payload.get("source_path"),
            created_at=payload.get("created_at", date.today().isoformat()),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ChangelogDocument":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Update run record (audit trail)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Output of the identity verification step."""

    passed: bool
    expected_hash: str
    actual_hash: str
    versions_checked: tuple[str, ...]

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        return (
            f"[{status}] identity check on {len(self.versions_checked)} prior "
            f"release(s): expected={self.expected_hash[:12]}..., "
            f"actual={self.actual_hash[:12]}..."
        )


@dataclass(frozen=True, slots=True)
class UpdateRun:
    """One complete update run, captured for the audit log."""

    release: ReleaseEntry
    preview: bool
    dry_run: bool
    document_id_before: str | None
    document_id_after: str | None | None
    verification: VerificationResult | None
    exported_paths: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "release": self.release.to_payload(),
            "preview": self.preview,
            "dry_run": self.dry_run,
            "document_id_before": self.document_id_before,
            "document_id_after": self.document_id_after,
            "verification": (
                {
                    "passed": self.verification.passed,
                    "expected_hash": self.verification.expected_hash,
                    "actual_hash": self.verification.actual_hash,
                    "versions_checked": list(self.verification.versions_checked),
                }
                if self.verification
                else None
            ),
            "exported_paths": list(self.exported_paths),
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Sorting helpers (kept private to models.py)
# ---------------------------------------------------------------------------


def _date_key(value: str) -> str:
    return value  # YYYY-MM-DD already sorts lexicographically.


def _semver_key(value: str) -> tuple[int, ...]:
    """Coarse semver ordering: (major, minor, patch). Pre-release sorts lower."""
    m = _SEMVER_RE.match(value)
    if not m:
        # Invalid versions already rejected at construction; treat as lowest.
        return (-1, -1, -1)
    return (
        int(m.group("major")),
        int(m.group("minor")),
        int(m.group("patch")),
    )


__all__ = [
    "ChangelogDocument",
    "HouseStyle",
    "Link",
    "ReleaseEntry",
    "ReleaseSection",
    "SectionItem",
    "UpdateRun",
    "VerificationResult",
]
