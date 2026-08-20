"""Fact tables, and the two places a fact table can come from.

A fact table is the whole tracked surface of a codebase at one point in time:
every declared fact, rendered to the exact string a document is expected to
contain. Everything this tool does is a comparison of two of them.

The "before" table can come from three places, and which one you have decides
what the tool can do:

* **a git revision** — ``--base main``. The honest default for "I am about to
  open a pull request"; it answers *what did this branch change*.
* **the recorded snapshot** — ``.docsync/state.json``, written after every
  successful apply. Answers *what has changed since the docs were last
  brought into step*, and needs no git at all.
* **another working directory** — mostly for tests and for repos that are not
  git repos.

The "after" table is nearly always the working tree, because the point is to
run this before you commit.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from docsync.extract import ExtractError, Value, extract, render
from docsync.registry import Registry


class SourceError(RuntimeError):
    pass


class Tree(Protocol):
    """Somewhere file contents can be read from."""

    name: str

    def read(self, relpath: str) -> str | None:
        """The file's text, or None if it is not present in this tree."""


@dataclass
class WorkingTree:
    root: Path
    name: str = "working tree"

    def read(self, relpath: str) -> str | None:
        path = self.root / relpath
        if not path.is_file():
            return None
        try:
            return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None


@dataclass
class DirectoryTree:
    root: Path
    name: str = "directory"

    def read(self, relpath: str) -> str | None:
        return WorkingTree(self.root).read(relpath)


@dataclass
class GitRevisionTree:
    """Files as they were at a revision, read with ``git show``.

    ``git show`` wants a path relative to the *repository* root, and the
    registry usually sits somewhere below it, so the prefix has to be resolved
    once and prepended. Getting this wrong produces "file not found at
    revision" for every fact, which reads exactly like a legitimate "these are
    all new facts" — a wrong answer that looks like a right one, so the prefix
    is computed from git rather than assumed.
    """

    root: Path
    revision: str
    name: str = ""
    _prefix: str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.name = self.name or f"revision {self.revision}"
        self._prefix = _git(self.root, "rev-parse", "--show-prefix").strip()
        # `rev-parse --verify` *exits non-zero* for an unknown revision rather
        # than printing nothing and succeeding, so the useful message has to be
        # built on the failure path. Checking only the stdout let git's own
        # "fatal: needed a single revision" reach the user instead.
        try:
            resolved = _git(
                self.root, "rev-parse", "--verify", "--quiet", f"{self.revision}^{{commit}}"
            ).strip()
        except SourceError:
            resolved = ""
        if not resolved:
            raise SourceError(
                f"{self.revision!r} is not a commit this repository knows about\n"
                f"  → try a branch name, a tag, HEAD~1, or a full sha"
            )
        self.name = f"revision {self.revision} ({resolved[:12]})"

    def read(self, relpath: str) -> str | None:
        try:
            return _git(self.root, "show", f"{self.revision}:{self._prefix}{relpath}")
        except SourceError:
            return None


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SourceError(
            "git is not on PATH, so --base cannot read a revision\n"
            "  → install git, or diff against the recorded snapshot instead "
            "(omit --base)"
        ) from exc
    if proc.returncode != 0:
        raise SourceError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def is_git_repo(root: Path) -> bool:
    try:
        return _git(root, "rev-parse", "--is-inside-work-tree").strip() == "true"
    except SourceError:
        return False


def is_dirty(root: Path, relpath: str) -> bool:
    """Does this file have uncommitted changes?

    Used to refuse to overwrite work in progress. A file git does not track at
    all counts as dirty: writing over an untracked document would destroy it
    with no way back, which is worse than the tracked case, not better.
    """
    try:
        prefix = _git(root, "rev-parse", "--show-prefix").strip()
        status = _git(root, "status", "--porcelain", "--", f"{prefix}{relpath}")
    except SourceError:
        return True  # cannot prove it is clean, so treat it as dirty
    return bool(status.strip())


# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactValue:
    key: str
    label: str
    is_list: bool
    raw: Value | None = None
    text: str | list[str] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def display(self) -> str:
        if self.error:
            return f"<unresolved: {self.error.splitlines()[0]}>"
        if isinstance(self.text, list):
            return ", ".join(self.text) if self.text else "<empty list>"
        return str(self.text)


@dataclass
class FactTable:
    origin: str
    values: dict[str, FactValue] = field(default_factory=dict)

    def __getitem__(self, key: str) -> FactValue:
        return self.values[key]

    def __contains__(self, key: str) -> bool:
        return key in self.values

    @property
    def errors(self) -> dict[str, str]:
        return {k: v.error for k, v in self.values.items() if v.error}

    def as_snapshot(self) -> dict[str, str | list[str]]:
        """The rendered values only — what gets recorded in state.json.

        Unresolved facts are left out rather than recorded as null. A snapshot
        is the baseline for the next comparison, and a null baseline would make
        the next run report a fabricated change from nothing to something.
        """
        return {k: v.text for k, v in self.values.items() if v.ok and v.text is not None}


def read_facts(registry: Registry, tree: Tree) -> FactTable:
    """Every declared fact, read out of one tree.

    Never raises for a single bad fact. One unreadable file must not hide the
    other nineteen facts, and the caller needs the whole picture to decide
    whether to stop — which it does, loudly, in ``plan``.
    """
    table = FactTable(origin=tree.name)
    for key, spec in registry.facts.items():
        text = tree.read(spec.source)
        if text is None:
            table.values[key] = FactValue(
                key=key,
                label=spec.label,
                is_list=spec.is_list,
                error=f"{spec.source} is not present in the {tree.name}",
            )
            continue
        try:
            raw = extract(spec.kind, spec.argument, text, source=spec.source)
            rendered = render(raw, spec.fmt)
        except ExtractError as exc:
            table.values[key] = FactValue(
                key=key, label=spec.label, is_list=spec.is_list, error=str(exc)
            )
            continue
        table.values[key] = FactValue(
            key=key, label=spec.label, is_list=spec.is_list, raw=raw, text=rendered
        )
    return table


def table_from_snapshot(registry: Registry, snapshot: dict[str, str | list[str]]) -> FactTable:
    """Rebuild a comparable table from recorded strings.

    A snapshot has no raw values — only the rendered text, which is all a
    comparison needs. A fact that has been *added to the registry* since the
    snapshot was taken is absent here, and is reported as such rather than
    treated as a change from empty.
    """
    table = FactTable(origin="recorded snapshot")
    for key, spec in registry.facts.items():
        if key not in snapshot:
            table.values[key] = FactValue(
                key=key,
                label=spec.label,
                is_list=spec.is_list,
                error="not in the recorded snapshot — this fact was added to the "
                "registry after the last apply",
            )
            continue
        table.values[key] = FactValue(
            key=key, label=spec.label, is_list=spec.is_list, text=snapshot[key]
        )
    return table
