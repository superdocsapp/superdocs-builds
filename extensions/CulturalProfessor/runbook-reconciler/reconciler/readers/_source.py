"""Where a fact came from, down to the line.

Rule 8 — a finding whose evidence does not resolve to a real file and line is a
bug — is the reason this module exists. A finding that says "the alert threshold
is 1.2" is an assertion; one that says
`fixtures/infra/platform-infra/monitoring/payments.rules.yml:7` is something an
engineer can check in ten seconds, and the difference decides whether the
findings get read at all.

PyYAML throws line numbers away during construction, so `load_yaml` re-attaches
them. It does that by handing back `dict` subclasses carrying a `line`
attribute rather than by injecting a `__line__` *key*, which is the usual trick
and a bad one: an injected key shows up in `.keys()`, in equality comparisons
and in anything that iterates the mapping, and it eventually ends up in output
somebody sees.

The cost is that these dicts are not `dict`s to `type()`, only to `isinstance()`.
Nothing here depends on exact type, and `yaml.safe_dump` handles them because it
registers a representer for dict subclasses. If that ever stops being true, the
fix is to copy into a plain dict at the boundary — not to reach for `__line__`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from reconciler.config import display_path


@dataclass(frozen=True)
class SourceRef:
    """A file and a line, both real."""

    file: str
    line: int

    def __str__(self) -> str:
        return f"{self.file}:{self.line}"

    @classmethod
    def of(cls, path: Path | str, node: Any = None, default_line: int = 1) -> SourceRef:
        return cls(display_path(path), line_of(node, default_line))


class LineDict(dict):
    """A mapping that remembers which line it started on."""

    line: int = 0


class _LineLoader(yaml.SafeLoader):
    pass


def _construct_mapping(loader: _LineLoader, node: yaml.MappingNode) -> LineDict:
    loader.flatten_mapping(node)
    data = LineDict(loader.construct_pairs(node, deep=True))
    data.line = node.start_mark.line + 1
    return data


_LineLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_yaml(path: Path) -> Any:
    """One YAML document, with mappings carrying their line numbers."""
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_LineLoader)


def load_yaml_all(path: Path) -> list[Any]:
    """Every document in a multi-document file.

    Kubernetes manifests are routinely several resources separated by `---` in
    one file, and reading only the first silently loses most of a cluster.
    """
    return [
        doc
        for doc in yaml.load_all(path.read_text(encoding="utf-8"), Loader=_LineLoader)
        if doc is not None
    ]


def line_of(node: Any, default: int = 1) -> int:
    return int(getattr(node, "line", default) or default)


def iter_files(roots: tuple[Path, ...], *patterns: str) -> list[Path]:
    """Every file under any configured repo root matching any pattern.

    Sorted, because two runs over the same estate must produce findings in the
    same order — an unsorted `rglob` makes the diff between two `rr check` runs
    look like the estate changed when only the filesystem's mood did.
    """
    found: set[Path] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            found.update(p for p in root.rglob(pattern) if p.is_file())
    return sorted(found)


__all__ = ["LineDict", "SourceRef", "iter_files", "line_of", "load_yaml", "load_yaml_all"]
