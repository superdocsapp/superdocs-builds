"""Choosing which documents a run looks at.

Three sources, in the order the tool actually gets used:

* explicit paths — what `pre-commit` passes on argv, already narrowed to staged files
* `--since <ref>` — a git diff, which is how CI narrows a pull request to what it changed
* the configured globs — the fallback for a deliberate whole-repository run

The first two are why the tool is fast in the places speed matters. The cache then removes the
work again for anything whose bytes have not changed since last time.
"""

from __future__ import annotations

import fnmatch
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .config import Config

MARKDOWN_SUFFIXES = frozenset({".md", ".mdx", ".markdown"})


class GitUnavailable(Exception):
    """`--since` was requested outside a git repository, or git is not installed."""


@dataclass(frozen=True)
class Target:
    """One document to check, with its bytes read once and reused."""

    path: Path
    relative: str
    data: bytes

    @property
    def text(self) -> str:
        return self.data.decode("utf-8", errors="replace")


def select_targets(
    config: Config,
    *,
    paths: Iterable[str] = (),
    since: str | None = None,
    limit: int = 0,
) -> tuple[list[Target], list[str]]:
    """Resolve the files to check. Returns `(targets, notes)`.

    `notes` records anything the caller should be told about rather than have silently applied -
    a sample limit that dropped files, for instance. Skipping work quietly is how a linter ends up
    reporting a clean repository it never looked at.
    """
    notes: list[str] = []

    if paths:
        candidates = [Path(p) for p in paths]
    elif since:
        candidates = _changed_since(config.root, since)
        notes.append(f"comparing against {since}")
    else:
        candidates = _glob(config)

    resolved = _filter(candidates, config)

    if limit and len(resolved) > limit:
        notes.append(
            f"sample mode: checking {limit} of {len(resolved)} files; "
            f"{len(resolved) - limit} not checked"
        )
        resolved = resolved[:limit]

    targets: list[Target] = []
    for path in resolved:
        try:
            data = path.read_bytes()
        except OSError as exc:
            notes.append(f"could not read {path}: {exc}")
            continue
        targets.append(Target(path=path, relative=_relative(path, config.root), data=data))
    return targets, notes


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _glob(config: Config) -> list[Path]:
    found: set[Path] = set()
    for pattern in config.include:
        found.update(p for p in config.root.glob(pattern) if p.is_file())
    return sorted(found)


def _filter(candidates: Iterable[Path], config: Config) -> list[Path]:
    """Keep existing Markdown files that no exclude pattern matches, de-duplicated and sorted."""
    # The style guide is never linted against itself. A guide that says `never write "utilise"`
    # has to quote the word it bans, and flagging it for doing so is both wrong and the kind of
    # thing that makes people delete the tool.
    styleguide = config.styleguide.resolve(config.root)

    kept: dict[Path, None] = {}
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else (config.root / candidate)
        if not path.is_file() or path.suffix.lower() not in MARKDOWN_SUFFIXES:
            continue
        resolved = path.resolve()
        if styleguide is not None and resolved == styleguide:
            continue
        if _is_excluded(_relative(path, config.root), config.exclude):
            continue
        kept.setdefault(resolved, None)
    return sorted(kept)


def _is_excluded(relative: str, patterns: Iterable[str]) -> bool:
    for pattern in patterns:
        if fnmatch.fnmatch(relative, pattern):
            return True
        # `**/node_modules/**` should also exclude a top-level `node_modules/x.md`, which plain
        # fnmatch does not match because it requires something before the first slash.
        if pattern.startswith("**/") and fnmatch.fnmatch(relative, pattern[3:]):
            return True
    return False


def _changed_since(root: Path, ref: str) -> list[Path]:
    """Files added, copied, modified or renamed since `ref`, plus staged and unstaged changes.

    Deleted files are excluded: there is nothing to lint, and a rule firing on a file the author
    just removed would be worse than useless.
    """
    changed: set[Path] = set()
    for args in (
        ["diff", "--name-only", "--diff-filter=ACMR", f"{ref}...HEAD"],
        ["diff", "--name-only", "--diff-filter=ACMR", ref],
        ["diff", "--name-only", "--diff-filter=ACMR", "--cached"],
        ["diff", "--name-only", "--diff-filter=ACMR"],
    ):
        for name in _git(root, args):
            changed.add(root / name)
    return sorted(changed)


def _git(root: Path, args: list[str]) -> list[str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise GitUnavailable("git is not installed, so --since cannot be used") from exc
    except subprocess.TimeoutExpired as exc:
        raise GitUnavailable("git did not respond within 30s") from exc

    if completed.returncode != 0:
        message = completed.stderr.strip() or "git failed"
        if "not a git repository" in message.lower():
            raise GitUnavailable(f"{root} is not a git repository, so --since cannot be used")
        # A ref that resolves for one form of diff and not another is normal; only a hard failure
        # on every form is worth reporting, and the caller sees that as an empty result.
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]
