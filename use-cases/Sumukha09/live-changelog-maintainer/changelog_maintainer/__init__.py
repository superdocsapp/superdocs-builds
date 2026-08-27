"""Living Changelog Maintainer.

A standing changelog document that receives a targeted update on every release,
leaving previous entries byte-identical. Powered by SuperDocs for surgical edits
and high-fidelity exports.
"""

from changelog_maintainer.models import (
    ChangelogDocument,
    HouseStyle,
    ReleaseEntry,
    ReleaseSection,
    SectionItem,
    UpdateRun,
)

__all__ = [
    "ChangelogDocument",
    "HouseStyle",
    "ReleaseEntry",
    "ReleaseSection",
    "SectionItem",
    "UpdateRun",
]

__version__ = "1.0.0"
