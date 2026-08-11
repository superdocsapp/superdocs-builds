"""The verdict cache: what makes the linter fast on files nobody touched.

The card asks for "fast on unchanged files". The honest way to deliver that is to answer from cache
only when the answer provably could not have changed, so the key covers all three inputs to a
verdict:

* the document's bytes
* the configuration fingerprint (severities, rule options, globs)
* the style guide's content hash, which is folded into that fingerprint

Change any of them and the key changes, so yesterday's answer is never reused for today's question.

Two verdicts are deliberately never cached. A `FAILED` file must be retried next run rather than
inheriting its failure, and a `SKIPPED` file was never examined at all - caching either would turn
a transient problem into a permanent one.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from .model import FileResult, Finding, Verdict, VerdictKind
from .state import STATE_DIRNAME, content_sha, write_atomic

CACHE_VERSION = 1


class CacheEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int = CACHE_VERSION
    path: str
    key: str
    verdict: Verdict
    findings: tuple[Finding, ...] = ()
    checks_run: tuple[str, ...] = ()


class VerdictCache:
    """A content-addressed store of previous verdicts under `<root>/.docs-lint/cache/`."""

    def __init__(self, root: Path, *, config_fingerprint: str, enabled: bool = True):
        self.dir = Path(root) / STATE_DIRNAME / "cache"
        self.config_fingerprint = config_fingerprint
        self.enabled = enabled
        self.hits = 0
        self.misses = 0

    def key_for(self, data: bytes) -> str:
        return content_sha(f"{CACHE_VERSION}:{self.config_fingerprint}:".encode() + data)

    def _path(self, key: str) -> Path:
        # Shard by prefix so a large repository does not put ten thousand files in one directory.
        return self.dir / key[:2] / f"{key}.json"

    def get(self, path: str, data: bytes) -> FileResult | None:
        if not self.enabled:
            return None
        entry_path = self._path(self.key_for(data))
        if not entry_path.is_file():
            self.misses += 1
            return None
        try:
            entry = CacheEntry.model_validate_json(entry_path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, json.JSONDecodeError):
            # A corrupt entry is a miss, not a crash. Re-checking is always safe; trusting a
            # half-written verdict is not.
            self.misses += 1
            entry_path.unlink(missing_ok=True)
            return None

        if entry.version != CACHE_VERSION:
            self.misses += 1
            return None

        self.hits += 1
        return FileResult(
            path=path,
            verdict=entry.verdict,
            findings=entry.findings,
            from_cache=True,
        )

    def put(self, result: FileResult, data: bytes) -> None:
        """Record a verdict, unless it is one that must not be remembered."""
        if not self.enabled or not self.is_cacheable(result.verdict):
            return
        key = self.key_for(data)
        entry = CacheEntry(
            path=result.path,
            key=key,
            verdict=result.verdict,
            findings=result.findings,
            checks_run=result.verdict.checks_run,
        )
        write_atomic(self._path(key), entry.model_dump_json(indent=2))

    @staticmethod
    def is_cacheable(verdict: Verdict) -> bool:
        """Only verdicts reached by actually examining the file.

        A failure caused by SuperDocs being briefly unreachable must not be remembered as this
        document's permanent verdict; the next run should try again.
        """
        return verdict.kind in {VerdictKind.CLEAN, VerdictKind.FINDINGS}

    def clear(self) -> int:
        removed = 0
        if not self.dir.is_dir():
            return 0
        for entry in self.dir.rglob("*.json"):
            entry.unlink(missing_ok=True)
            removed += 1
        return removed

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
