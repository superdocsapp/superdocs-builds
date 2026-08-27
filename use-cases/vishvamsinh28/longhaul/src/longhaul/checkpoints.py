"""Fault injection for the proof suite.

A checkpoint is a named instant in the step lifecycle. In a normal run every call
here is a cheap no-op. Under the proof harness two environment variables turn them
into instruments:

``LONGHAUL_TRACE=<path>``
    Append every checkpoint the run actually reaches, in order. The proof suite runs
    the job once in trace mode and derives its kill-point list from the result, so the
    list can never be cherry-picked or drift away from the code.

``LONGHAUL_KILL_AT=<name>``
    On reaching that checkpoint, send ``SIGKILL`` to our own pid.

``SIGKILL`` and not an exception, and not ``sys.exit``: an exception unwinds through
``finally`` blocks and flushes buffers, which is precisely the cleanup a crashed
process never gets to do. Testing with a catchable failure would prove a weaker
property than the one claimed. There is no handler for ``SIGKILL``; the process stops
between two instructions with whatever was still in userspace buffers lost.
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

ENV_TRACE = "LONGHAUL_TRACE"
ENV_KILL_AT = "LONGHAUL_KILL_AT"


def checkpoint(name: str) -> None:
    """Mark a named instant. Traces it, or dies here, or does nothing."""
    trace_path = os.environ.get(ENV_TRACE)
    if trace_path:
        _append_trace(trace_path, name)

    kill_at = os.environ.get(ENV_KILL_AT)
    if kill_at and kill_at == name:
        _die(name)


def _append_trace(path: str, name: str) -> None:
    # Opened and fsynced per call: the tracing run must survive being killed too,
    # since a kill-point run also traces what it reached before dying.
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(name + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _die(name: str) -> None:
    marker = os.environ.get("LONGHAUL_KILL_MARKER")
    if marker:
        # Tell the harness the kill point was genuinely reached, so a kill that
        # never fired is a test failure rather than a silently passing no-op.
        Path(marker).write_text(name, encoding="utf-8")
    sys.stderr.write(f"longhaul: SIGKILL at checkpoint {name}\n")
    sys.stderr.flush()
    os.kill(os.getpid(), signal.SIGKILL)
    # Unreachable. SIGKILL cannot be caught, blocked, or ignored.
    raise AssertionError("SIGKILL did not terminate the process")  # pragma: no cover


def step_checkpoint(step_index: int, stage: str) -> str:
    """Checkpoint names are per-step so a kill point identifies one exact instant."""
    return f"step{step_index:03d}.{stage}"


def read_trace(path: str | os.PathLike[str]) -> list[str]:
    p = Path(path)
    if not p.exists():
        return []
    return [line for line in p.read_text(encoding="utf-8").splitlines() if line]
