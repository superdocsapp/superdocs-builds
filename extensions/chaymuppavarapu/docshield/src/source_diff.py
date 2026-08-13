from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourceChange:
    category: str
    path: str
    before: Any
    after: Any


@dataclass(frozen=True)
class SourceDiff:
    """
    Semantic differences between protected source structures.

    Content changes can be ignored while structural changes remain
    visible to the validator.
    """

    changes: tuple[SourceChange, ...]

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    @property
    def change_count(self) -> int:
        return len(self.changes)


def compare_values(
    before: Any,
    after: Any,
    path: str = "root",
) -> list[SourceChange]:
    """
    Recursively compare two JSON-like structures.

    This function is intentionally generic so it can be used for
    LaTeX metadata, DOCX metadata, and future document adapters.
    """

    changes: list[SourceChange] = []

    if type(before) is not type(after):
        changes.append(
            SourceChange(
                category="type",
                path=path,
                before=before,
                after=after,
            )
        )
        return changes

    if isinstance(before, dict):
        keys = sorted(
            set(before) | set(after),
            key=str,
        )

        for key in keys:
            child_path = f"{path}.{key}"

            if key not in before:
                changes.append(
                    SourceChange(
                        category="added",
                        path=child_path,
                        before=None,
                        after=after[key],
                    )
                )
                continue

            if key not in after:
                changes.append(
                    SourceChange(
                        category="removed",
                        path=child_path,
                        before=before[key],
                        after=None,
                    )
                )
                continue

            changes.extend(
                compare_values(
                    before[key],
                    after[key],
                    child_path,
                )
            )

        return changes

    if isinstance(before, (list, tuple)):
        maximum = max(
            len(before),
            len(after),
        )

        for index in range(maximum):
            child_path = f"{path}[{index}]"

            if index >= len(before):
                changes.append(
                    SourceChange(
                        category="added",
                        path=child_path,
                        before=None,
                        after=after[index],
                    )
                )
                continue

            if index >= len(after):
                changes.append(
                    SourceChange(
                        category="removed",
                        path=child_path,
                        before=before[index],
                        after=None,
                    )
                )
                continue

            changes.extend(
                compare_values(
                    before[index],
                    after[index],
                    child_path,
                )
            )

        return changes

    if before != after:
        changes.append(
            SourceChange(
                category="changed",
                path=path,
                before=before,
                after=after,
            )
        )

    return changes


def diff_source_structure(
    before: dict[str, Any],
    after: dict[str, Any],
) -> SourceDiff:
    """
    Compare protected structural metadata.
    """

    return SourceDiff(
        changes=tuple(
            compare_values(
                before,
                after,
            )
        )
    )
