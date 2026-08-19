"""Proof that an edit changed only the section it was aimed at.

Every instruction this tool sends ends with "Change nothing outside this section."
Saying it is not the same as showing it, and the brief is explicit about the difference:
*measure, do not claim; byte-identical where you promise untouched.* So the document is
fingerprinted between turns, and a turn that moves a section it was not aimed at fails the
run rather than passing quietly.

Exports cost no operations, so the evidence is free — only the seconds spent fetching it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

_SECTION = re.compile(r"^##\s+(.+?)\s*$")

# A hosted image arrives as a pre-signed URL whose signature is regenerated on every
# export. That is a credential, not content, so it is dropped before hashing — otherwise
# the curve's section would read as edited on every single turn.
_SIGNED = re.compile(r"(\((?:https?:)//[^)?\s]+)\?[^)\s]*(\))")


def _content(lines: list[str]) -> str:
    """The section's text, with layout normalised away.

    Blank-line placement and trailing spaces are how the exporter breathes, not what the
    document says. Everything else — every word, number and citation — is compared.
    """
    body = "\n".join(stripped for line in lines if (stripped := line.strip()))
    return _SIGNED.sub(r"\1\2", body)


def fingerprints(markdown: str) -> dict[str, str]:
    """One hash per numbered section of the exported report."""
    out: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in markdown.replace("\r", "").split("\n"):
        found = _SECTION.match(line)
        if found:
            if current is not None:
                out[current] = hashlib.sha256(_content(buf).encode("utf-8")).hexdigest()[:12]
            current, buf = found.group(1), []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = hashlib.sha256(_content(buf).encode("utf-8")).hexdigest()[:12]
    return out


def moved(before: dict[str, str], after: dict[str, str]) -> set[str]:
    """Every section whose content is not what it was, appearances and losses included."""
    return {
        name
        for name in set(before) | set(after)
        if before.get(name) != after.get(name)
    }


@dataclass
class SurgicalReport:
    """What each turn was aimed at, and what it actually touched."""

    turns: int = 0
    collateral: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.collateral

    def record(self, aimed_at: str, before: dict[str, str], after: dict[str, str]) -> list[str]:
        self.turns += 1
        stray = sorted(moved(before, after) - {aimed_at})
        self.collateral += [f"editing “{aimed_at}” also changed “{s}”" for s in stray]
        return stray

    def summary(self) -> str:
        if not self.turns:
            return "no edits to check"
        if self.clean:
            return f"{self.turns} turns, every edit confined to its own section"
        return f"{self.turns} turns, {len(self.collateral)} unintended change(s)"
