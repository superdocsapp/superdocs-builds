"""The hash chain: append, verify, and — the point of the exercise — detect tampering.

PLAN.md §8 asks for "a tamper test that must fail after mutating a middle entry
— proving the property rather than claiming it." That is `test_edited_middle_
entry_is_detected` and the three that follow it.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from gateway.audit import (
    GENESIS,
    AuditChainError,
    AuditLog,
    canonical,
    entry_hash,
    read_entries,
    verify_chain,
)


def _write_entries(path: Path, count: int) -> AuditLog:
    log = AuditLog(path, fsync=False)
    for i in range(count):
        log.append({"team": "legal", "tool": "chat_async", "decision": "allowed", "seq": i})
    return log


def _lines(path: Path) -> list[str]:
    return path.read_text().splitlines()


def _rewrite(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n")


# ──── Appending ──────────────────────────────────────────────────────────


def test_empty_log_verifies_clean(tmp_path: Path) -> None:
    result = verify_chain(tmp_path / "nothing.jsonl")
    assert result.ok
    assert result.entries == 0
    assert result.head == GENESIS


def test_first_entry_chains_to_genesis(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 1)
    entry = json.loads(_lines(path)[0])
    assert entry["prev"] == GENESIS


def test_each_entry_chains_to_the_last(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)
    entries = [e for _, e in read_entries(path)]
    for earlier, later in itertools.pairwise(entries):
        assert later["prev"] == earlier["hash"]


def test_append_adds_timestamp(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 1)
    assert "ts" in json.loads(_lines(path)[0])


def test_head_tracks_last_hash(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = _write_entries(path, 3)
    assert log.head == json.loads(_lines(path)[-1])["hash"]
    assert verify_chain(path).head == log.head


def test_chain_survives_reopening(tmp_path: Path) -> None:
    """A restarted gateway must continue the chain, not start a second one."""
    path = tmp_path / "audit.jsonl"
    first = _write_entries(path, 3)

    reopened = AuditLog(path, fsync=False)
    assert reopened.head == first.head
    reopened.append({"team": "legal", "decision": "allowed", "seq": 99})

    result = verify_chain(path)
    assert result.ok
    assert result.entries == 4


def test_verify_counts_all_entries(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 12)
    assert verify_chain(path).entries == 12


# ──── Tamper detection ───────────────────────────────────────────────────


def test_edited_middle_entry_is_detected(tmp_path: Path) -> None:
    """Mutate one field of entry 3 of 5. Verify must fail, and name line 3."""
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)
    assert verify_chain(path).ok

    lines = _lines(path)
    entry = json.loads(lines[2])
    entry["decision"] = "denied_tool"  # rewrite history: pretend we blocked it
    lines[2] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    _rewrite(path, lines)

    result = verify_chain(path)
    assert not result.ok
    assert result.broken_line == 3
    assert "modified" in (result.reason or "")


def test_rehashed_entry_still_breaks_the_next_link(tmp_path: Path) -> None:
    """The interesting case: a tamperer who knows to recompute the hash.

    Editing entry 3 and fixing its own hash makes line 3 self-consistent — so
    the break moves to line 4, whose `prev` now points at a hash that no longer
    exists. Concealing the edit means rewriting every entry that follows it.
    """
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)

    lines = _lines(path)
    entry = json.loads(lines[2])
    entry["decision"] = "denied_tool"
    entry["hash"] = entry_hash(entry["prev"], entry)
    lines[2] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    _rewrite(path, lines)

    result = verify_chain(path)
    assert not result.ok
    assert result.broken_line == 4
    assert "broken link" in (result.reason or "")


def test_deleted_entry_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)

    lines = _lines(path)
    del lines[2]
    _rewrite(path, lines)

    result = verify_chain(path)
    assert not result.ok
    assert result.broken_line == 3
    assert "broken link" in (result.reason or "")


def test_reordered_entries_are_detected(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)

    lines = _lines(path)
    lines[1], lines[2] = lines[2], lines[1]
    _rewrite(path, lines)

    assert not verify_chain(path).ok


def test_truncated_tail_is_still_verifiable(tmp_path: Path) -> None:
    """Losing the END of the log is not tampering — the prefix stays valid."""
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 5)

    lines = _lines(path)
    _rewrite(path, lines[:3])

    result = verify_chain(path)
    assert result.ok
    assert result.entries == 3


def test_malformed_line_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 3)

    lines = _lines(path)
    lines[1] = "{not json"
    _rewrite(path, lines)

    result = verify_chain(path)
    assert not result.ok
    assert result.broken_line == 2
    assert "malformed" in (result.reason or "")


def test_entry_missing_hash_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 2)

    lines = _lines(path)
    entry = json.loads(lines[0])
    del entry["hash"]
    lines[0] = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    _rewrite(path, lines)

    result = verify_chain(path)
    assert not result.ok
    assert "missing 'hash'" in (result.reason or "")


def test_appending_to_corrupt_tail_refuses(tmp_path: Path) -> None:
    """A corrupted last line must not silently restart the chain from genesis."""
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 3)

    lines = _lines(path)
    lines[-1] = "{truncated"
    _rewrite(path, lines)

    with pytest.raises(AuditChainError, match="cannot be read"):
        AuditLog(path, fsync=False)


# ──── Canonical form ─────────────────────────────────────────────────────


def test_canonical_form_is_key_order_independent(tmp_path: Path) -> None:
    a = {"team": "legal", "tool": "chat", "prev": GENESIS}
    b = {"prev": GENESIS, "tool": "chat", "team": "legal"}
    assert canonical(a) == canonical(b)


def test_canonical_excludes_the_hash_field(tmp_path: Path) -> None:
    entry = {"team": "legal", "prev": GENESIS}
    without = canonical(entry)
    assert canonical({**entry, "hash": "deadbeef"}) == without


def test_written_line_round_trips_to_identical_bytes(tmp_path: Path) -> None:
    """Verification re-serialises parsed entries, so this must hold exactly."""
    path = tmp_path / "audit.jsonl"
    _write_entries(path, 3)
    for raw, (_, entry) in zip(_lines(path), read_entries(path), strict=True):
        assert json.dumps(entry, sort_keys=True, separators=(",", ":")) == raw
