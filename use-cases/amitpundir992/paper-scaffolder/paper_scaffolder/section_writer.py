"""Pluggable section-writing boundary."""

from __future__ import annotations

from typing import Mapping, Protocol


class SectionWriter(Protocol):
    """Interface implemented by deterministic or future external writers."""

    def generate(self, section_title: str, evidence: Mapping[str, str]) -> str:
        """Return a draft based only on the supplied evidence."""


class ExtractiveSectionWriter:
    """Safe default writer that returns supplied evidence without embellishment."""

    def generate(self, section_title: str, evidence: Mapping[str, str]) -> str:
        del section_title
        return "\n\n".join(evidence.values())
