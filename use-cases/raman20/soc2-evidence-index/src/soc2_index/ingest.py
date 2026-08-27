from __future__ import annotations

import unicodedata
from pathlib import Path

import yaml

from soc2_index.extract import extract_metadata
from soc2_index.injection import load_patterns, scan
from soc2_index.models import EvidenceFile
from soc2_index.paths import mapping_rules_path
from soc2_index.runstore import sha256_file

_TEXT_EXT = {".md", ".txt", ".html", ".htm"}


class IngestError(Exception):
    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def _load_ignore(rules_path: Path | None) -> list[str]:
    data = yaml.safe_load((rules_path or mapping_rules_path()).read_text(encoding="utf-8"))
    return list(data.get("ignore_globs") or [])


def _ignored(rel: str, globs: list[str]) -> bool:
    from fnmatch import fnmatch

    name = Path(rel).name
    for g in globs:
        if fnmatch(rel, g) or fnmatch(name, g):
            return True
        if g.endswith("/**") and (rel.startswith(g[:-3]) or f"/{g[:-3]}" in f"/{rel}"):
            # ".git/**" or "expected/**"
            prefix = g[:-3].rstrip("/")
            parts = Path(rel).parts
            if prefix in parts or rel.startswith(prefix + "/"):
                return True
    return False


def walk(root: Path, rules_path: Path | None = None) -> list[EvidenceFile]:
    root = root.resolve()
    if not root.is_dir():
        raise IngestError(f"evidence root is not a directory: {root}")
    globs = _load_ignore(rules_path)
    patterns = load_patterns()
    files: list[EvidenceFile] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name.startswith("."):
            continue
        rel = path.relative_to(root).as_posix()
        rel = unicodedata.normalize("NFC", rel)
        if rel.startswith("./"):
            rel = rel[2:]
        if "::" in rel:
            raise IngestError(f"evidence path contains '::': {rel}")
        try:
            path.resolve().relative_to(root)
        except ValueError as exc:
            raise IngestError(f"path escapes evidence root: {rel}") from exc
        if _ignored(rel, globs):
            continue
        digest = sha256_file(path)
        ext = path.suffix.lower()
        text: str | None
        if ext in _TEXT_EXT:
            text = path.read_text(encoding="utf-8", errors="replace")
        else:
            text = None
        meta = extract_metadata(path, text)
        flags = scan(text or "", patterns) if text is not None else []
        files.append(
            EvidenceFile(
                relative_path=rel,
                sha256=digest,
                size_bytes=path.stat().st_size,
                title=meta["title"],
                date=meta["date"],
                owner=meta["owner"],
                front_matter_controls=meta["front_matter_controls"],
                front_matter_has_controls_key=meta["front_matter_has_controls_key"],
                evidence_type=meta["evidence_type"],
                extract_status=meta["extract_status"],
                injection_flags=flags,
            )
        )
    return files
