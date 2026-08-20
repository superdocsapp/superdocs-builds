"""The registry: what is a fact, and which document claims to carry it.

Two declarations, deliberately kept in different places.

**``docsync.yaml`` declares facts.** A fact is a named value with a file to
read it from and an extractor to read it with. It is about the *code*, so it
lives with the code, in one file somebody can audit.

**Each document declares its own coverage**, in front matter. Coverage is
about the *prose*, so it belongs next to the prose. The person adding a
paragraph about the retry policy to a runbook is the person who knows the
runbook now carries ``retry.max_attempts``, and they should be able to say so
without opening a central registry and without a reviewer having to notice.

The cross-check between the two is ``docsync audit``: every covered key must
be a declared fact, and every declared fact should be carried by at least one
document. A fact nothing covers is not an error — it is a documentation gap,
reported as one.

A document with no ``docsync:`` block in its front matter is not managed. That
is the default, so dropping this tool into a docs tree does nothing until
somebody opts a document in.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from docsync.extract import ExtractError, is_list_kind, parse_extractor


class RegistryError(RuntimeError):
    def __init__(self, message: str, *, fix: str | None = None) -> None:
        super().__init__(message if not fix else f"{message}\n  → {fix}")
        self.fix = fix


@dataclass(frozen=True)
class FactSpec:
    key: str
    label: str
    source: str  # repo-relative, forward slashes
    kind: str
    argument: str
    fmt: str = "{value}"

    @property
    def is_list(self) -> bool:
        return is_list_kind(self.kind)


@dataclass(frozen=True)
class DocumentSpec:
    path: str  # repo-relative, forward slashes
    title: str
    covers: tuple[str, ...]


@dataclass
class Registry:
    root: Path
    facts: dict[str, FactSpec] = field(default_factory=dict)
    doc_globs: tuple[str, ...] = ("docs/**/*.md",)
    session_id: str = ""
    budget: int = 40

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> Registry:
        path = Path(path).resolve()
        if path.is_dir():
            path = path / "docsync.yaml"
        if not path.exists():
            raise RegistryError(
                f"no registry at {path}",
                fix="create a docsync.yaml — see the README, or copy example/docsync.yaml",
            )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise RegistryError(f"{path} is not valid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise RegistryError(f"{path} must contain a YAML mapping at the top level")

        root = path.parent
        version = raw.get("version", 1)
        if version != 1:
            raise RegistryError(
                f"{path} declares version {version!r}, and this build understands version 1"
            )

        facts: dict[str, FactSpec] = {}
        raw_facts = raw.get("facts") or {}
        if not isinstance(raw_facts, dict):
            raise RegistryError("`facts` must be a mapping of key → definition")
        if not raw_facts:
            raise RegistryError(
                f"{path} declares no facts",
                fix="a registry with no facts can never propose an edit; add at least one",
            )
        for key, body in raw_facts.items():
            facts[str(key)] = _fact_spec(str(key), body, root)

        globs = raw.get("doc_globs") or ["docs/**/*.md"]
        if isinstance(globs, str):
            globs = [globs]
        if not isinstance(globs, list) or not all(isinstance(g, str) for g in globs):
            raise RegistryError("`doc_globs` must be a string or a list of strings")

        budget = raw.get("budget", 40)
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
            raise RegistryError("`budget` must be a non-negative whole number of operations")

        session = raw.get("session") or f"docsync-{_slug(root.name)}"
        if not isinstance(session, str) or not session.strip():
            raise RegistryError("`session` must be a non-empty string")

        return cls(
            root=root,
            facts=facts,
            doc_globs=tuple(globs),
            session_id=session.strip(),
            budget=budget,
        )

    # -- documents ---------------------------------------------------------

    def documents(self) -> list[DocumentSpec]:
        """Every managed document on disk, in a stable order.

        Managed means "has a ``docsync.covers`` list in its front matter". A
        document that names a key this registry does not declare is an error
        rather than a skip: a typo in a coverage list would otherwise silently
        exclude the document from every future change, which is the exact
        failure this tool is supposed to prevent.
        """
        found: dict[str, DocumentSpec] = {}
        for pattern in self.doc_globs:
            for path in sorted(self.root.glob(pattern)):
                if not path.is_file():
                    continue
                rel = _relative_inside(path, self.root, what="document")
                if rel in found:
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                covers, title = coverage_of(text)
                if covers is None:
                    continue
                unknown = [key for key in covers if key not in self.facts]
                if unknown:
                    raise RegistryError(
                        f"{rel} declares coverage of unknown fact(s): {', '.join(unknown)}",
                        fix=f"declared facts are: {', '.join(sorted(self.facts)) or 'none'}",
                    )
                found[rel] = DocumentSpec(
                    path=rel, title=title or Path(rel).stem, covers=tuple(covers)
                )
        return [found[key] for key in sorted(found)]

    def documents_carrying(self, key: str) -> list[DocumentSpec]:
        return [doc for doc in self.documents() if key in doc.covers]

    def uncovered_facts(self) -> list[str]:
        covered = {key for doc in self.documents() for key in doc.covers}
        return sorted(set(self.facts) - covered)

    def resolve(self, relpath: str) -> Path:
        """A repo-relative path, checked to be inside the repo."""
        candidate = (self.root / relpath).resolve()
        try:
            candidate.relative_to(self.root.resolve())
        except ValueError:
            raise RegistryError(
                f"{relpath!r} resolves outside the registry root",
                fix="every path in docsync.yaml must stay inside the directory holding it",
            ) from None
        return candidate


# ---------------------------------------------------------------------------
# Front matter
# ---------------------------------------------------------------------------

_FRONT_MATTER = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
_HTML_BLOCK = re.compile(r"<!--\s*docsync:\s*\r?\n(.*?)-->", re.S)
_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.M)


def coverage_of(text: str) -> tuple[list[str] | None, str]:
    """``(covers, title)`` for a document, or ``(None, title)`` if unmanaged.

    Two spellings are accepted. Markdown front matter is the one to reach for::

        ---
        title: Retry and dead-lettering
        docsync:
          covers: [retry.max_attempts, retry.backoff_seconds]
        ---

    and an HTML comment block does the same job in a file where a ``---``
    fence would render::

        <!-- docsync:
        covers: [retry.max_attempts]
        -->

    Both are parsed as YAML. A block that is present but malformed raises,
    because "I wrote a coverage list and this tool ignored it" is precisely
    the silent failure worth being loud about.
    """
    title = ""
    block: str | None = None
    source = ""

    match = _FRONT_MATTER.match(text)
    if match:
        source = "front matter"
        try:
            data = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError as exc:
            raise RegistryError(f"front matter is not valid YAML: {exc}") from exc
        if isinstance(data, dict):
            if isinstance(data.get("title"), str):
                title = data["title"].strip()
            inner = data.get("docsync")
            if inner is not None:
                block = "inline"
                covers = _covers_from(inner, source)
                return covers, title or _first_heading(text)

    html = _HTML_BLOCK.search(text)
    if html:
        source = "docsync HTML comment"
        try:
            data = yaml.safe_load(html.group(1)) or {}
        except yaml.YAMLError as exc:
            raise RegistryError(f"{source} is not valid YAML: {exc}") from exc
        block = "html"
        covers = _covers_from(data, source)
        return covers, title or _first_heading(text)

    _ = block
    return None, title or _first_heading(text)


def _covers_from(data: object, source: str) -> list[str]:
    if not isinstance(data, dict):
        raise RegistryError(f"the docsync block in {source} must be a mapping")
    covers = data.get("covers")
    if covers is None:
        raise RegistryError(
            f"the docsync block in {source} has no `covers` list",
            fix="either list the facts this document carries, or remove the block "
            "so the document is left unmanaged",
        )
    if isinstance(covers, str):
        covers = [covers]
    if not isinstance(covers, list) or not all(isinstance(c, str) for c in covers):
        raise RegistryError(f"`covers` in {source} must be a list of fact keys")
    seen: list[str] = []
    for key in covers:
        key = key.strip()
        if key and key not in seen:
            seen.append(key)
    return seen


def _first_heading(text: str) -> str:
    match = _HEADING.search(text)
    return match.group(1).strip() if match else ""


# ---------------------------------------------------------------------------


def _fact_spec(key: str, body: object, root: Path) -> FactSpec:
    if not isinstance(body, dict):
        raise RegistryError(f"fact {key!r} must be a mapping with `from` and `extract`")
    source = body.get("from")
    if not isinstance(source, str) or not source.strip():
        raise RegistryError(f"fact {key!r} needs a `from:` path to read")
    source = source.strip().replace("\\", "/")
    _relative_inside((root / source), root, what=f"fact {key!r}")

    spec = body.get("extract")
    try:
        kind, argument = parse_extractor(spec if isinstance(spec, str) else "")
    except ExtractError as exc:
        raise RegistryError(f"fact {key!r}: {exc}") from exc

    fmt = body.get("format", "{value}")
    if not isinstance(fmt, str):
        raise RegistryError(f"fact {key!r}: `format` must be a string")
    if "{value}" not in fmt:
        raise RegistryError(
            f"fact {key!r}: `format` must contain {{value}}",
            fix="a format without the placeholder produces the same text for every "
            "value, which would make every comparison pass",
        )

    label = body.get("label") or key
    if not isinstance(label, str):
        raise RegistryError(f"fact {key!r}: `label` must be a string")

    return FactSpec(
        key=key, label=label.strip(), source=source, kind=kind, argument=argument, fmt=fmt
    )


def _relative_inside(path: Path, root: Path, *, what: str) -> str:
    """Confirm a path stays inside the root, and return it repo-relative.

    Not paranoia. A registry is a checked-in file that this tool reads and
    whose contents it uploads to a third-party API; ``from: ../../../.ssh/id_rsa``
    in a pull request from a stranger should fail loudly rather than helpfully
    read the file.
    """
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise RegistryError(
            f"{what} points outside the registry root: {path}",
            fix="paths in docsync.yaml are relative to the directory holding it and "
            "may not escape it",
        ) from None
    return rel.as_posix()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "repo"
