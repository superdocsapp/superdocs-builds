"""Durable run state, atomic persistence, and per-file locks.

This module exists for one requirement: kill the process mid-run, start it again, and no finished
work is lost and nothing already paid for is paid for twice.

Three things make that work.

*Every transition is written before it is acted on.* A job id is persisted the instant SuperDocs
issues it, before the first poll. A crash one millisecond later still leaves a resumable record;
without that ordering, the run would restart the edit and be billed a second time.

*Writes are atomic.* Temp file in the same directory, flush, fsync, `os.replace`. A state file is
therefore always either the old version or the new one, never a half-written mixture. A torn state
file would be worse than no state file at all, because it would resume into nonsense.

*Files are locked, not just tracked.* Two runs over the same repository must not both spend an
operation linting the same document.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .model import Finding, Verdict

STATE_DIRNAME = ".docs-lint"


class Stage(StrEnum):
    """Where one file has got to.

    The order matters: `resume` restarts a file from its recorded stage, so each stage must name
    work that is genuinely already finished and durably recorded.
    """

    PENDING = "pending"
    LOCAL_CHECKED = "local_checked"
    UPLOADED = "uploaded"
    JOB_STARTED = "job_started"
    AWAITING_REVIEW = "awaiting_review"
    DONE = "done"

    @property
    def is_finished(self) -> bool:
        return self is Stage.DONE


class FileState(BaseModel):
    """Everything needed to resume one file without redoing or re-buying anything."""

    model_config = ConfigDict(frozen=True)

    path: str
    content_sha: str
    stage: Stage = Stage.PENDING
    findings: tuple[Finding, ...] = ()
    verdict: Verdict | None = None
    #: Each document gets its own session, because a job parked awaiting review holds its session
    #: against every other request (BUGS.md #8).
    session_id: str | None = None
    #: Persisted the moment SuperDocs issues it, before the first poll. This is the field that
    #: makes a resumed run free rather than double-billed.
    job_id: str | None = None
    ops_charged: int = 0
    seconds: float = 0.0
    from_cache: bool = False

    def advanced(self, stage: Stage, **updates) -> FileState:
        return self.model_copy(update={"stage": stage, **updates})


class RunState(BaseModel):
    """The whole run, as persisted between stages."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    mode: str = "check"
    created_at: str = ""
    updated_at: str = ""
    #: Config and style-guide fingerprint. A resume whose config has changed is refused rather
    #: than silently mixing verdicts made under two different rule sets.
    config_fingerprint: str = ""
    files: tuple[FileState, ...] = ()
    stage_seconds: dict[str, float] = Field(default_factory=dict)
    degraded: tuple[str, ...] = ()

    @staticmethod
    def new(*, mode: str, config_fingerprint: str, files: tuple[FileState, ...]) -> RunState:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        return RunState(
            run_id=f"{datetime.now(UTC):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}",
            mode=mode,
            created_at=stamp,
            updated_at=stamp,
            config_fingerprint=config_fingerprint,
            files=files,
        )

    def file(self, path: str) -> FileState | None:
        return next((f for f in self.files if f.path == path), None)

    def with_file(self, updated: FileState) -> RunState:
        files = tuple(updated if f.path == updated.path else f for f in self.files)
        return self.model_copy(
            update={"files": files, "updated_at": datetime.now(UTC).isoformat(timespec="seconds")}
        )

    def with_degraded(self, note: str) -> RunState:
        if note in self.degraded:
            return self
        return self.model_copy(update={"degraded": (*self.degraded, note)})

    def with_stage_time(self, stage: str, seconds: float) -> RunState:
        timings = dict(self.stage_seconds)
        timings[stage] = timings.get(stage, 0.0) + seconds
        return self.model_copy(update={"stage_seconds": timings})

    @property
    def unfinished(self) -> tuple[FileState, ...]:
        return tuple(f for f in self.files if not f.stage.is_finished)

    @property
    def ops_charged(self) -> int:
        return sum(f.ops_charged for f in self.files)


class RunStore:
    """Reads and writes run state under `<root>/.docs-lint/`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.base = self.root / STATE_DIRNAME

    # -- paths ----------------------------------------------------------------------

    @property
    def runs_dir(self) -> Path:
        return self.base / "runs"

    @property
    def locks_dir(self) -> Path:
        return self.base / "locks"

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "state.json"

    # -- persistence ----------------------------------------------------------------

    def save(self, state: RunState) -> None:
        """Persist atomically. Called after every transition, never batched."""
        path = self.state_path(state.run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, state.model_dump_json(indent=2))

    def load(self, run_id: str) -> RunState:
        path = self.state_path(run_id)
        if not path.is_file():
            raise FileNotFoundError(f"No such run: {run_id} (looked in {path})")
        return RunState.model_validate_json(path.read_text(encoding="utf-8"))

    def list_runs(self) -> list[str]:
        """Run ids, newest first. Ids start with a timestamp, so this sorts chronologically."""
        if not self.runs_dir.is_dir():
            return []
        return sorted(
            (d.name for d in self.runs_dir.iterdir() if (d / "state.json").is_file()),
            reverse=True,
        )

    def latest_run_id(self) -> str | None:
        runs = self.list_runs()
        return runs[0] if runs else None

    # -- locks ----------------------------------------------------------------------

    @contextmanager
    def lock_file(self, path: str, *, run_id: str, steal_after: float = 3600.0) -> Iterator[bool]:
        """Try to take an exclusive lock on one document. Yields whether it was acquired.

        Yielding False rather than raising is deliberate: a file another run is already checking is
        not an error, it is a file this run should skip and report as skipped. The alternative -
        both runs linting it - would spend two operations to learn the same thing.

        Locks are files created with O_EXCL, so acquisition is atomic even across processes. A lock
        whose owning process is gone is stolen, so a crashed run cannot wedge the repository
        forever; that is the same failure mode as BUGS.md #8, and it should not be reproduced here.
        """
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(path.encode()).hexdigest()[:16]
        lock_path = self.locks_dir / f"{digest}.lock"
        acquired = False
        try:
            acquired = self._acquire(lock_path, path=path, run_id=run_id, steal_after=steal_after)
            yield acquired
        finally:
            if acquired:
                lock_path.unlink(missing_ok=True)

    def _acquire(self, lock_path: Path, *, path: str, run_id: str, steal_after: float) -> bool:
        payload = json.dumps(
            {"path": path, "run_id": run_id, "pid": os.getpid(), "acquired_at": time.time()}
        )
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            if not self._is_stale(lock_path, steal_after=steal_after):
                return False
            lock_path.unlink(missing_ok=True)
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except OSError:
                return False  # somebody else won the race to steal it; let them have it
        with os.fdopen(fd, "w") as handle:
            handle.write(payload)
        return True

    @staticmethod
    def _is_stale(lock_path: Path, *, steal_after: float) -> bool:
        try:
            info = json.loads(lock_path.read_text())
        except (OSError, ValueError):
            return True  # unreadable lock is a broken lock
        if time.time() - float(info.get("acquired_at", 0)) > steal_after:
            return True
        pid = info.get("pid")
        return not (isinstance(pid, int) and _process_alive(pid))


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by somebody else
    except OSError:
        return True
    return True


def write_atomic(path: Path, text: str) -> None:
    """Write a file so readers see either the old contents or the new, never a mixture.

    fsync before the rename is what makes this survive a power loss rather than only a crash; the
    directory fsync afterwards is what makes the rename itself durable. Both are cheap here and the
    thing being protected is the record of work already paid for.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def content_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
