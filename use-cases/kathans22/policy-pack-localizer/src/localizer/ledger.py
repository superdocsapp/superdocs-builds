"""Records operation counts and idempotency state for cost accounting."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parents[2] / "state"
LEDGER_PATH = STATE_DIR / "ledger.json"


@dataclass
class LedgerEntry:
    step: str
    subject: str
    operations: int
    wall_time: float
    status: str = "CHARGED"
    content_key: str | None = None


class OperationCeilingExceeded(RuntimeError):
    """Raised when a run's charged operations exceed the configured ceiling."""


def ops_from_response(response: dict) -> int:
    """Operations actually billed for one chat response, per its own `usage` field.

    SuperDocs does not bill a chat call uniformly: a preview-only call
    (`approval_mode='ask_every_time'`, nothing applied yet) comes back with
    `usage: null` — free. Only a call that actually applies a change comes
    back with `usage.was_billable: true` and a real `ops_charged`. Charging
    a flat 1 per chat call (the original assumption here) overcounts every
    preview. Callers computing `chat_calls` for `record()` should pass this,
    not a hardcoded constant.
    """
    usage = response.get("usage") or {}
    if usage.get("was_billable"):
        return usage.get("ops_charged") or 1
    return 0


class Ledger:
    """The run's cost record: one entry per step, operations charged, wall time.

    Charging follows CLAUDE.md's economics section: a chat call that actually
    applies a change is 1 operation; everything else (lock/hash, upload,
    export, download, ack rendering, and a preview-only chat call) is 0.
    Callers report the number of operations a step actually spent via
    `chat_calls` — see `ops_from_response()` to derive that from a real
    SuperDocs response rather than assuming a constant.
    """

    def __init__(self):
        self.entries: list[LedgerEntry] = []

    def record(
        self,
        step: str,
        subject: str,
        chat_calls: int,
        wall_time: float,
        content_key: str | None = None,
        output_exists: bool = True,
    ) -> LedgerEntry:
        """Record a step, or skip it if already charged and its output still exists.

        Idempotency guard: when `content_key` was already charged in a prior
        run (see `already_charged`) and `output_exists` is True — the caller
        confirms the previous output is still on disk — the step is recorded
        as SKIPPED with 0 operations rather than billed again.
        """
        if content_key is not None and output_exists and self.already_charged(content_key):
            entry = LedgerEntry(
                step=step, subject=subject, operations=0, wall_time=wall_time,
                status="SKIPPED", content_key=content_key,
            )
        else:
            entry = LedgerEntry(
                step=step, subject=subject, operations=chat_calls, wall_time=wall_time,
                status="CHARGED", content_key=content_key,
            )
        self.entries.append(entry)
        return entry

    def already_charged(self, content_key: str) -> bool:
        """True if `content_key` was already billed (status CHARGED) in this ledger."""
        return any(
            e.content_key == content_key and e.status == "CHARGED" for e in self.entries
        )

    def enforce_ceiling(self, ceiling: int | None) -> None:
        """Abort the run if operations charged so far exceed `ceiling`.

        Checked by the caller after each record() during a run, not just at
        the end — the point is to stop mid-run before further operations are
        spent, not to report the overrun after the fact.
        """
        if ceiling is not None and self.total_operations > ceiling:
            raise OperationCeilingExceeded(
                f"Operations charged ({self.total_operations}) exceeded the configured "
                f"ceiling ({ceiling}). Fix: raise the ceiling if this run is expected "
                "to cost more, or stop and investigate why more operations were "
                "charged than planned."
            )

    @property
    def total_operations(self) -> int:
        return sum(e.operations for e in self.entries)

    def save(self, path: Path = LEDGER_PATH) -> Path:
        """Persist entries to state/ so a resumed run does not double-count."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps([asdict(e) for e in self.entries], indent=2), encoding="utf-8"
        )
        return path

    @classmethod
    def load(cls, path: Path = LEDGER_PATH) -> "Ledger":
        """Load a previously saved ledger, or start empty if none exists yet."""
        ledger = cls()
        if path.exists():
            raw = json.loads(path.read_text(encoding="utf-8"))
            ledger.entries = [LedgerEntry(**entry) for entry in raw]
        return ledger

    def report(self) -> str:
        """Print and return the aligned run-cost table: one line per step, a total."""
        lines = [_format_line(f"[{e.step}]", e.subject, e.operations, e.status) for e in self.entries]
        lines.append(" " * (_LINE_WIDTH - len(_RULE)) + _RULE)
        lines.append(_format_line("", "total", self.total_operations, "CHARGED", label_is_total=True))
        text = "\n".join(lines)
        print(text)
        return text


_LINE_WIDTH = 62
_RULE = "-" * 7
_TAG_WIDTH = 12


def _format_ops(n: int) -> str:
    return f"{n} op" if n == 1 else f"{n} ops"


def _format_line(tag: str, subject: str, operations: int, status: str, label_is_total: bool = False) -> str:
    label = subject if label_is_total else f"{tag:<{_TAG_WIDTH}}{subject}"
    ops_text = _format_ops(operations)
    if status == "SKIPPED":
        ops_text = f"SKIPPED ({ops_text})"
    pad = max(1, _LINE_WIDTH - len(label) - len(ops_text))
    return f"{label}{' ' * pad}{ops_text}"


def apply_limit(countries: list, limit: int | None) -> list:
    """Small-sample mode: return only the first `limit` countries, or all of them."""
    if limit is None:
        return list(countries)
    return list(countries)[:limit]


def parse_limit(argv: list[str]) -> int | None:
    """Extract an integer --limit N (or --limit=N) value from a CLI argument list."""
    for i, arg in enumerate(argv):
        if arg == "--limit" and i + 1 < len(argv):
            return int(argv[i + 1])
        if arg.startswith("--limit="):
            return int(arg.split("=", 1)[1])
    return None
