"""
Idempotency / graceful re-entry for both builds — the task doc's general
standard ("idempotency wherever an operation costs money", "resumes
without losing work or duplicating it") applies across the whole round,
not just Task 1.

Approach: one small JSON state file per input, keyed by a stable id
derived from the input itself (so re-running with the SAME input resumes;
a genuinely different input gets a fresh run). Persists the session_id
(so we don't re-upload) and which stages/entries already completed (so we
don't re-approve/re-pay for them).
"""
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


class RunState:
    def __init__(self, state_path: Path):
        self.state_path = state_path
        if state_path.exists():
            self._data = json.loads(state_path.read_text(encoding="utf-8"))
        else:
            self._data = {"session_id": None, "completed": []}
        self._lock_file = None

    def acquire_lock(self, timeout: float = 30.0) -> None:
        """Acquire an exclusive OS lock for this logical run."""
        lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(lock_path, "a+", encoding="utf-8")
        deadline = time.monotonic() + timeout
        try:
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out waiting for run lock: {lock_path}")
                        time.sleep(0.1)
            else:
                import fcntl

                while True:
                    try:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise TimeoutError(f"Timed out waiting for run lock: {lock_path}")
                        time.sleep(0.1)
            self._lock_file = lock_file
        except BaseException:
            lock_file.close()
            raise

    def release_lock(self) -> None:
        if self._lock_file is None:
            return
        if os.name == "nt":
            import msvcrt

            self._lock_file.seek(0)
            msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        self._lock_file.close()
        self._lock_file = None

    def reload(self) -> None:
        """Reload the checkpoint after acquiring the run lock."""
        if self.state_path.exists():
            self._data = json.loads(self.state_path.read_text(encoding="utf-8"))

    @property
    def session_id(self) -> str | None:
        return self._data.get("session_id")

    def set_session_id(self, session_id: str) -> None:
        self._data["session_id"] = session_id
        self._save()

    def is_completed(self, item_key: str) -> bool:
        return item_key in self._data["completed"]

    @property
    def completed_count(self) -> int:
        return len(self._data["completed"])

    def mark_completed(self, item_key: str) -> None:
        if item_key not in self._data["completed"]:
            self._data["completed"].append(item_key)
        self._save()  # save after EVERY item, not just at the end — a crash
        # between items must not lose the items that already succeeded

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            prefix=f".{self.state_path.name}.",
            dir=self.state_path.parent,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temporary_file:
                json.dump(self._data, temporary_file, indent=2)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, self.state_path)
        finally:
            if os.path.exists(temporary_path):
                os.unlink(temporary_path)

    def reset(self) -> None:
        self._data = {"session_id": None, "completed": []}
        if self.state_path.exists():
            self.state_path.unlink()


def state_path_for(out_dir: Path, stable_key: str) -> Path:
    """stable_key should be something that identifies THIS logical run
    (e.g. the input file's content hash, or a HACCP plan's product name)
    — not a random uuid, or every run would look 'new' and resumability
    would never trigger."""
    digest = hashlib.sha256(stable_key.encode()).hexdigest()[:16]
    return out_dir / f".run_state_{digest}.json"