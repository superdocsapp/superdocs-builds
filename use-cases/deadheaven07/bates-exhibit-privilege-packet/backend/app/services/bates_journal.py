"""Filesystem Bates journal: crash-recovery backbone.

Bates assignment is the one operation that MUST be continuous: a crash
mid-assignment must never leave gaps or double-stamped pages. This journal
records every assignment as an fsync'd JSON line so a killed worker can
resume exactly where it stopped, and the final state can be proven
mathematically (zero gaps, zero duplicates, exactly one label per page).
"""

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JournalEntry:
    page_key: str
    document_id: str
    page_number: int
    bates_number: int
    bates_label: str
    assigned_at: str


@dataclass(frozen=True)
class ContinuityProof:
    valid: bool
    start: int
    end: int
    expected_count: int
    gaps: list[int]
    duplicates: list[int]
    double_stamped_pages: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


class BatesJournal:
    """Append-only, line-oriented journal with fsync after every entry.

    Crash safety: a worker appends + fsyncs each entry before continuing, so
    at most the in-flight page is lost; on resume, already-journaled pages
    are skipped and numbering continues at `last_number + 1`.
    """

    def __init__(self, path: Path):
        self.path = Path(path)

    def append(self, entry: JournalEntry) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")
            f.flush()
            import os

            os.fsync(f.fileno())

    def entries(self) -> list[JournalEntry]:
        if not self.path.exists():
            return []
        entries: list[JournalEntry] = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entries.append(JournalEntry(**data))
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Skipping malformed journal line in {self.path}: {e}")
        return entries

    def page_keys(self) -> set[str]:
        return {e.page_key for e in self.entries()}

    def last_number(self) -> int | None:
        entries = self.entries()
        if not entries:
            return None
        return max(e.bates_number for e in entries)

    def resume_start(self, bates_start_number: int) -> int:
        last = self.last_number()
        return (last + 1) if last is not None else bates_start_number

    def prove_continuity(
        self,
        expected_count: int,
        bates_start_number: int = 1,
    ) -> ContinuityProof:
        """Mathematically prove the journaled sequence is gap-free and
        duplicate-free, and that no page carries two labels."""
        entries = self.entries()
        numbers = sorted(e.bates_number for e in entries)
        expected = list(range(bates_start_number, bates_start_number + expected_count))

        gaps = [n for n in expected if n not in set(numbers)]
        duplicates = [n for n in numbers if numbers.count(n) > 1]

        by_page: dict[str, list[int]] = {}
        for e in entries:
            by_page.setdefault(e.page_key, []).append(e.bates_number)
        double_stamped = [k for k, v in by_page.items() if len(v) > 1]

        valid = numbers == expected and not gaps and not duplicates and not double_stamped
        return ContinuityProof(
            valid=valid,
            start=min(numbers) if numbers else bates_start_number,
            end=max(numbers) if numbers else bates_start_number - 1,
            expected_count=expected_count,
            gaps=sorted(gaps),
            duplicates=sorted(set(duplicates)),
            double_stamped_pages=sorted(double_stamped),
        )
