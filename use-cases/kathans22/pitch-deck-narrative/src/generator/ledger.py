"""Records operation counts and wall time for cost accounting.

Ported from Build 1's ledger, adapted to verticals (not countries).
Charging follows CLAUDE.md: a chat call that applies a change is typically 1 op;
export / download / divergence scoring are 0. Idempotent by content key so a
vertical already generated for the current manifest version is not regenerated.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parents[2] / "state"
LEDGER_PATH = STATE_DIR / "ledger.json"


@dataclass
class LedgerEntry:
    step: str
    vertical: str
    operations: int
    wall_time: float
    status: str = "CHARGED"
    content_key: str | None = None


class OperationCeilingExceeded(RuntimeError):
    """Raised when a run's charged operations exceed the configured ceiling."""


def ops_from_response(response: dict) -> int:
    """Operations actually billed for one chat response, per its own ``usage`` field.

    Preview-only calls can return ``usage: null`` (free). Only a call with
    ``usage.was_billable: true`` charges. Never assume a flat 1 per chat call.
    """
    usage = response.get("usage") or {}
    if usage.get("was_billable"):
        return usage.get("ops_charged") or 1
    return 0


class Ledger:
    """The run's cost record: one entry per step, operations charged, wall time."""

    def __init__(self) -> None:
        self.entries: list[LedgerEntry] = []

    def record(
        self,
        step: str,
        vertical: str,
        chat_calls: int,
        wall_time: float,
        content_key: str | None = None,
        output_exists: bool = True,
    ) -> LedgerEntry:
        """Record a step, or skip it if already charged and its output still exists.

        Idempotency: when ``content_key`` was already CHARGED and ``output_exists``
        is True, record SKIPPED with 0 operations rather than billing again.
        """
        if content_key is not None and output_exists and self.already_charged(content_key):
            entry = LedgerEntry(
                step=step,
                vertical=vertical,
                operations=0,
                wall_time=wall_time,
                status="SKIPPED",
                content_key=content_key,
            )
        else:
            entry = LedgerEntry(
                step=step,
                vertical=vertical,
                operations=chat_calls,
                wall_time=wall_time,
                status="CHARGED",
                content_key=content_key,
            )
        self.entries.append(entry)
        return entry

    def already_charged(self, content_key: str) -> bool:
        """True if ``content_key`` was already billed (status CHARGED) in this ledger."""
        return any(
            e.content_key == content_key and e.status == "CHARGED" for e in self.entries
        )

    def enforce_ceiling(self, ceiling: int | None) -> None:
        """Abort the run if operations charged so far exceed ``ceiling``.

        Checked after each ``record()`` during a run — stop before more ops are spent.
        """
        if ceiling is not None and self.total_operations > ceiling:
            raise OperationCeilingExceeded(
                f"Operations charged ({self.total_operations}) exceeded the configured "
                f"ceiling ({ceiling}). Fix: raise OPS_BUDGET_CAP / --ops-ceiling if this "
                "run is expected to cost more, or stop and investigate overspend."
            )

    @property
    def total_operations(self) -> int:
        return sum(e.operations for e in self.entries)

    def save(self, path: Path = LEDGER_PATH) -> Path:
        """Persist entries to state/ so a resumed run does not double-count."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(e) for e in self.entries], indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: Path = LEDGER_PATH) -> Ledger:
        """Load a previously saved ledger, or start empty if none exists yet."""
        ledger = cls()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            ledger.entries = [LedgerEntry(**entry) for entry in raw]
        return ledger

    def report(self) -> str:
        """Print and return the aligned run-cost table: one line per step, a total."""
        lines = [
            _format_line(f"[{e.step}]", e.vertical, e.operations, e.status)
            for e in self.entries
        ]
        lines.append(" " * (_LINE_WIDTH - len(_RULE)) + _RULE)
        lines.append(
            _format_line("", "total", self.total_operations, "CHARGED", label_is_total=True)
        )
        text = "\n".join(lines)
        print(text)
        return text


_LINE_WIDTH = 62
_RULE = "-" * 7
_TAG_WIDTH = 14


def _format_ops(n: int) -> str:
    return f"{n} op" if n == 1 else f"{n} ops"


def _format_line(
    tag: str,
    vertical: str,
    operations: int,
    status: str,
    label_is_total: bool = False,
) -> str:
    label = vertical if label_is_total else f"{tag:<{_TAG_WIDTH}}{vertical}"
    ops_text = _format_ops(operations)
    if status == "SKIPPED":
        ops_text = f"SKIPPED ({ops_text})"
    pad = max(1, _LINE_WIDTH - len(label) - len(ops_text))
    return f"{label}{' ' * pad}{ops_text}"


def apply_limit(items: list, limit: int | None) -> list:
    """Small-sample mode: return only the first ``limit`` items, or all of them."""
    if limit is None:
        return list(items)
    return list(items)[:limit]


def parse_limit(argv: list[str]) -> int | None:
    """Extract an integer ``--limit N`` (or ``--limit=N``) from a CLI argument list."""
    for i, arg in enumerate(argv):
        if arg == "--limit" and i + 1 < len(argv):
            return int(argv[i + 1])
        if arg.startswith("--limit="):
            return int(arg.split("=", 1)[1])
    return None


def parse_ops_ceiling(argv: list[str] | None = None) -> int | None:
    """Operation ceiling from ``--ops-ceiling`` or env ``OPS_BUDGET_CAP``."""
    if argv:
        for i, arg in enumerate(argv):
            if arg == "--ops-ceiling" and i + 1 < len(argv):
                return int(argv[i + 1])
            if arg.startswith("--ops-ceiling="):
                return int(arg.split("=", 1)[1])
    raw = os.environ.get("OPS_BUDGET_CAP")
    if raw is None or raw.strip() == "":
        return None
    return int(raw)
