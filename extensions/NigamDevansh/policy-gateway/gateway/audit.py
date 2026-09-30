# A hash-chained, append-only audit log.
#
# Each line embeds the hash of the line before it, so removing an entry, editing
# one in place, or reordering two of them all break the chain at a point
# `verify` can name. This is tamper-EVIDENT, not tamper-proof: someone with
# write access to the file can rewrite every entry from the break onward and
# produce a clean chain again. What it buys is that they cannot do it *quietly*
# — the final hash changes, so a hash pinned anywhere else (a nightly log ship,
# a monitoring check, a screenshot in a ticket) no longer matches.
#
# Content is deliberately excluded. Entries record the SHA-256 of the request
# body, never the body: an audit log that quotes the documents it guards is a
# second copy of the data the gateway exists to protect.

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# The `prev` of the first entry. Not a real hash — nothing precedes it.
GENESIS = "0" * 64

_HASH_FIELD = "hash"
_PREV_FIELD = "prev"


class AuditChainError(RuntimeError):
    """Raised when an existing log cannot be safely appended to."""


class AuditWriteError(RuntimeError):
    """The entry could not be persisted.

    The gateway treats this as fatal for the request in flight and fails
    closed. The whole claim of this service is that every call is on the
    record; quietly serving traffic it cannot record would break that claim at
    exactly the moment it matters most, and a storage fault that only shows up
    as a silent gap in a log is a fault nobody notices for weeks.
    """


def canonical(entry: dict[str, Any]) -> str:
    """The exact bytes that get hashed, and the exact bytes written to disk.

    Sorted keys and no whitespace, so that parsing a line and re-serialising it
    reproduces the original byte-for-byte. Verification depends on that: it
    re-derives each hash from the parsed dict, not from the raw line, and the
    two must agree.
    """
    body = {k: v for k, v in entry.items() if k != _HASH_FIELD}
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def entry_hash(prev: str, entry: dict[str, Any]) -> str:
    """sha256(prev || canonical(entry)).

    `prev` is also stored inside the entry, so it is covered twice — once as a
    field and once as the prefix. The redundancy is free and makes each line
    self-describing: you can check a single line without its neighbour.
    """
    return hashlib.sha256(prev.encode() + canonical(entry).encode()).hexdigest()


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    entries: int
    broken_line: int | None = None
    reason: str | None = None
    head: str | None = None

    def describe(self) -> str:
        if self.ok:
            return f"chain intact — {self.entries} entries, head {self.head or GENESIS}"
        return f"chain BROKEN at line {self.broken_line}: {self.reason}"


class AuditLog:
    """Append-only writer over a JSONL file."""

    def __init__(self, path: str | os.PathLike[str], *, fsync: bool = True) -> None:
        # Absolute, so that every error message names a path an operator can
        # act on. A container reporting "directory data is not writable" sends
        # someone hunting for a working directory they cannot see.
        self._path = Path(path).resolve()
        self._fsync = fsync
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = _tail_hash(self._path)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def head(self) -> str:
        """Hash of the most recent entry — the value worth pinning elsewhere."""
        return self._prev

    def preflight(self) -> None:
        """Cheap writability check, run BEFORE the request is forwarded.

        This is what makes failing closed honest rather than cruel. Checking
        only at write time would mean discovering the fault *after* the call
        reached SuperDocs and billed — refusing then would tell the client
        "failed" about work that actually happened. Checking first means the
        common faults are caught while refusing is still free.

        It does not catch everything: a full disk is only discovered by
        writing. `append` raises for that case, and README.md documents the
        (narrow) window where an upstream call may have completed.
        """
        directory = self._path.parent
        if not directory.is_dir():
            raise AuditWriteError(
                f"audit log directory {directory} does not exist (is the data volume mounted?)"
            )
        if not os.access(directory, os.W_OK):
            raise AuditWriteError(f"audit log directory {directory} is not writable")
        if self._path.exists() and not os.access(self._path, os.W_OK):
            raise AuditWriteError(f"audit log {self._path} is not writable")

    def append(self, fields: dict[str, Any]) -> str:
        """Write one entry and return its hash.

        Locked because the chain is a shared mutable value: two concurrent
        requests reading the same `prev` would produce two entries claiming the
        same predecessor, and one of them would be a break.
        """
        with self._lock:
            entry = dict(fields)
            entry.setdefault("ts", datetime.now(UTC).isoformat())
            entry[_PREV_FIELD] = self._prev
            entry[_HASH_FIELD] = entry_hash(self._prev, entry)

            line = json.dumps(entry, sort_keys=True, separators=(",", ":"))
            try:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                    f.flush()
                    # An audit entry that is only in the page cache when the
                    # host loses power is an audit entry that never existed.
                    # The benchmark harness turns this off; production must not.
                    if self._fsync:
                        os.fsync(f.fileno())
            except OSError as exc:
                # `self._prev` is deliberately NOT advanced: the next append
                # must chain onto the last entry that actually reached disk.
                raise AuditWriteError(
                    f"could not write audit entry to {self._path}: {exc.strerror or exc}"
                ) from exc

            self._prev = entry[_HASH_FIELD]
            return self._prev


def read_entries(path: str | os.PathLike[str]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yield (line_number, entry) pairs, skipping blank lines."""
    p = Path(path)
    if not p.exists():
        return
    with p.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue
            yield lineno, json.loads(raw)


def verify_chain(path: str | os.PathLike[str]) -> VerifyResult:
    """Walk the chain and report the FIRST break.

    Three distinct failures are detected, and they are worth naming separately
    because they point at different things:

      * a line that will not parse        → truncation or a partial write
      * `prev` != the previous line's hash → an entry was deleted or reordered
      * a recomputed hash that disagrees   → an entry was edited in place
    """
    p = Path(path)
    if not p.exists():
        return VerifyResult(ok=True, entries=0, head=GENESIS)

    prev = GENESIS
    count = 0

    with p.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, start=1):
            raw = raw.strip()
            if not raw:
                continue

            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as exc:
                return VerifyResult(False, count, lineno, f"malformed JSON ({exc.msg})")

            if not isinstance(entry, dict):
                return VerifyResult(False, count, lineno, "entry is not an object")

            stored = entry.get(_HASH_FIELD)
            if not isinstance(stored, str):
                return VerifyResult(False, count, lineno, "missing 'hash' field")

            claimed_prev = entry.get(_PREV_FIELD)
            if claimed_prev != prev:
                return VerifyResult(
                    False,
                    count,
                    lineno,
                    f"broken link — entry claims prev={_short(claimed_prev)}, "
                    f"previous entry hashed to {_short(prev)}",
                )

            recomputed = entry_hash(prev, entry)
            if recomputed != stored:
                return VerifyResult(
                    False,
                    count,
                    lineno,
                    f"content was modified — stored hash {_short(stored)}, "
                    f"recomputed {_short(recomputed)}",
                )

            prev = stored
            count += 1

    return VerifyResult(ok=True, entries=count, head=prev)


def _tail_hash(path: Path) -> str:
    """The hash to chain the next entry onto.

    A log that exists but whose last line is unreadable is NOT quietly restarted
    from genesis — that would let a truncating attacker reset the chain by
    corrupting one line. The gateway refuses to open it and the operator runs
    `verify` to find out what happened.
    """
    if not path.exists() or path.stat().st_size == 0:
        return GENESIS

    last = None
    with path.open(encoding="utf-8") as f:
        for raw in f:
            raw = raw.strip()
            if raw:
                last = raw

    if last is None:
        return GENESIS

    try:
        entry = json.loads(last)
        head = entry[_HASH_FIELD]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AuditChainError(
            f"{path} ends with an entry that cannot be read ({exc}). "
            f"Refusing to append — run `gateway audit verify {path}` first."
        ) from None

    if not isinstance(head, str):
        raise AuditChainError(f"{path} ends with a non-string hash. Refusing to append.")
    return head


def _short(h: Any) -> str:
    s = str(h)
    return s[:12] + "…" if len(s) > 12 else s
