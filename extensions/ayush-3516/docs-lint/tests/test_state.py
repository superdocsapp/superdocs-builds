"""Tests for durable state and locking.

These cover the machinery that makes a killed run resumable and two concurrent runs safe. The
end-to-end proofs (a real SIGKILL, two real processes) come later against the runner; these pin the
primitives those proofs rely on.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from docs_lint.model import Verdict
from docs_lint.state import (
    FileState,
    RunState,
    RunStore,
    Stage,
    content_sha,
    write_atomic,
)


def state_with(tmp_path, *paths) -> RunState:
    return RunState.new(
        mode="check",
        config_fingerprint="fp1",
        files=tuple(FileState(path=p, content_sha=content_sha(p.encode())) for p in paths),
    )


# -- atomic writes ------------------------------------------------------------------


def test_write_atomic_replaces_contents_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "state.json"
    write_atomic(target, "first")
    write_atomic(target, "second")

    assert target.read_text() == "second"
    assert list(tmp_path.iterdir()) == [target], "a stray .tmp file would litter the repository"


def test_a_failed_write_leaves_the_previous_contents_intact(tmp_path, monkeypatch):
    """A torn state file would resume into nonsense, which is worse than no state file."""
    target = tmp_path / "state.json"
    write_atomic(target, "good")

    def explode(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(OSError):
        write_atomic(target, "doomed")

    assert target.read_text() == "good"
    assert list(tmp_path.iterdir()) == [target], "the temp file must be cleaned up on failure"


# -- run state ----------------------------------------------------------------------


def test_state_survives_a_save_and_load_round_trip(tmp_path):
    store = RunStore(tmp_path)
    state = state_with(tmp_path, "a.md", "b.md")
    store.save(state)

    loaded = store.load(state.run_id)
    assert loaded == state


def test_a_persisted_job_id_is_what_makes_a_resume_free(tmp_path):
    """The field that stops a resumed run paying twice for the same edit."""
    store = RunStore(tmp_path)
    state = state_with(tmp_path, "a.md")
    advanced = state.with_file(
        state.file("a.md").advanced(
            Stage.JOB_STARTED, session_id="sess-a", job_id="job-123", ops_charged=1
        )
    )
    store.save(advanced)

    resumed = store.load(state.run_id).file("a.md")
    assert resumed.job_id == "job-123"
    assert resumed.session_id == "sess-a"
    assert resumed.stage is Stage.JOB_STARTED


def test_unfinished_lists_exactly_the_work_a_resume_must_redo(tmp_path):
    state = state_with(tmp_path, "a.md", "b.md", "c.md")
    state = state.with_file(
        state.file("a.md").advanced(Stage.DONE, verdict=Verdict.clean(checks_run=("local",)))
    )
    assert [f.path for f in state.unfinished] == ["b.md", "c.md"]


def test_each_document_carries_its_own_session(tmp_path):
    """One session per document, because a parked review blocks its whole session."""
    state = state_with(tmp_path, "a.md", "b.md")
    state = state.with_file(state.file("a.md").advanced(Stage.UPLOADED, session_id="sess-a"))
    state = state.with_file(state.file("b.md").advanced(Stage.UPLOADED, session_id="sess-b"))

    sessions = {f.session_id for f in state.files}
    assert sessions == {"sess-a", "sess-b"}
    assert len(sessions) == len(state.files)


def test_run_ids_sort_newest_first(tmp_path):
    store = RunStore(tmp_path)
    ids = []
    for _ in range(3):
        state = state_with(tmp_path, "a.md")
        store.save(state)
        ids.append(state.run_id)

    listed = store.list_runs()
    assert set(listed) == set(ids)
    assert listed == sorted(ids, reverse=True)
    assert store.latest_run_id() == listed[0]


def test_loading_an_unknown_run_says_where_it_looked(tmp_path):
    with pytest.raises(FileNotFoundError, match="No such run"):
        RunStore(tmp_path).load("nope")


def test_degraded_notes_are_recorded_once(tmp_path):
    state = state_with(tmp_path, "a.md")
    state = state.with_degraded("SuperDocs unreachable").with_degraded("SuperDocs unreachable")
    assert state.degraded == ("SuperDocs unreachable",)


def test_stage_timings_accumulate(tmp_path):
    state = state_with(tmp_path, "a.md")
    state = state.with_stage_time("local", 1.5).with_stage_time("local", 0.5)
    assert state.stage_seconds["local"] == 2.0


def test_ops_charged_totals_across_files(tmp_path):
    state = state_with(tmp_path, "a.md", "b.md")
    state = state.with_file(state.file("a.md").advanced(Stage.DONE, ops_charged=1))
    state = state.with_file(state.file("b.md").advanced(Stage.DONE, ops_charged=2))
    assert state.ops_charged == 3


# -- locks --------------------------------------------------------------------------


def test_two_runs_cannot_hold_the_same_document(tmp_path):
    """Otherwise both would spend an operation learning the same thing."""
    store = RunStore(tmp_path)
    with store.lock_file("docs/a.md", run_id="run-1") as first:
        assert first
        with store.lock_file("docs/a.md", run_id="run-2") as second:
            assert not second


def test_different_documents_lock_independently(tmp_path):
    store = RunStore(tmp_path)
    with (
        store.lock_file("docs/a.md", run_id="run-1") as first,
        store.lock_file("docs/b.md", run_id="run-2") as second,
    ):
        assert first and second


def test_a_lock_is_released_when_the_run_finishes_with_it(tmp_path):
    store = RunStore(tmp_path)
    with store.lock_file("docs/a.md", run_id="run-1") as acquired:
        assert acquired
    with store.lock_file("docs/a.md", run_id="run-2") as acquired_again:
        assert acquired_again


def test_a_lock_is_released_even_when_the_body_raises(tmp_path):
    store = RunStore(tmp_path)
    with pytest.raises(RuntimeError), store.lock_file("docs/a.md", run_id="run-1"):
        raise RuntimeError("boom")

    with store.lock_file("docs/a.md", run_id="run-2") as acquired:
        assert acquired, "a crash inside the lock must not wedge the file forever"


def test_a_lock_held_by_a_dead_process_is_stolen(tmp_path):
    """A crashed run must not wedge the repository the way a parked session does."""
    store = RunStore(tmp_path)
    store.locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = next(iter(_lock_path_for(store, "docs/a.md")))
    lock_path.write_text(
        json.dumps({"path": "docs/a.md", "run_id": "dead", "pid": 999_999, "acquired_at": 1.0})
    )

    with store.lock_file("docs/a.md", run_id="run-2") as acquired:
        assert acquired


def test_an_unreadable_lock_is_treated_as_broken(tmp_path):
    store = RunStore(tmp_path)
    store.locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = next(iter(_lock_path_for(store, "docs/a.md")))
    lock_path.write_text("not json at all")

    with store.lock_file("docs/a.md", run_id="run-2") as acquired:
        assert acquired


def test_a_fresh_lock_held_by_a_live_process_is_not_stolen(tmp_path):
    store = RunStore(tmp_path)
    with (
        store.lock_file("docs/a.md", run_id="run-1"),
        store.lock_file("docs/a.md", run_id="run-2") as second,
    ):
        assert not second, "the owning process is alive and recent; the lock is real"


def test_a_very_old_lock_is_stolen_even_from_a_live_process(tmp_path):
    """Deliberate: liveness alone is not enough.

    A process that is alive but wedged - hung on a network call, stopped in a debugger - would
    otherwise hold a document hostage indefinitely. The age ceiling is the escape hatch, and it is
    an hour by default so it never fires during normal work.
    """
    store = RunStore(tmp_path)
    with (
        store.lock_file("docs/a.md", run_id="run-1"),
        store.lock_file("docs/a.md", run_id="run-2", steal_after=0.0) as second,
    ):
        assert second


def _lock_path_for(store: RunStore, path: str) -> list[Path]:
    import hashlib

    digest = hashlib.sha256(path.encode()).hexdigest()[:16]
    return [store.locks_dir / f"{digest}.lock"]
