"""Two sources that disagree, both quoted, neither preferred.

There is no `resolution`, no `resolved`, no `correct_value`, no `preferred_side`,
no `status` and no `approved` on anything in this module - and there is a test
that proves it by reflection rather than by reading. Decision 15's argument,
rebuilt for a document builder: a rule in a docstring is broken by the next
contributor by accident; a type with nowhere to write an opinion is not.

Sides are ordered by source path, a stable and meaningless order. Ordering by
credibility would be a resolution smuggled in through the ordering.
"""

from __future__ import annotations

from dataclasses import dataclass

from .figures import AnyFigure, Cite


@dataclass(frozen=True)
class Side:
    source: str  # corpus-relative path
    says: str  # what this source says, in words
    cites: tuple[Cite, ...]
    figures: tuple[AnyFigure, ...] = ()
    searched: int = 0  # how many locations were examined, when the side is an absence

    def __post_init__(self) -> None:
        if not self.cites:
            raise ValueError(
                f"{self.source}: a side of a disagreement that cannot cite its own bytes is "
                f"not evidence, and a disagreement missing a side is not emitted at all"
            )


@dataclass(frozen=True)
class Disagreement:
    about: str
    sides: tuple[Side, ...]

    def __post_init__(self) -> None:
        if len(self.sides) < 2:
            raise ValueError(
                f"{self.about}: a disagreement needs at least two sides, each with its own "
                f"citations. One side is an observation, not a disagreement."
            )
        ordered = tuple(sorted(self.sides, key=lambda s: s.source))
        object.__setattr__(self, "sides", ordered)

    def sentence(self) -> str:
        return " ".join(f"{s.source} says: {s.says}" for s in self.sides)
