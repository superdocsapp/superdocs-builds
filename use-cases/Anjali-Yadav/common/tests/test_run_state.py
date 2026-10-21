import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from run_state import RunState, state_path_for  # noqa: E402


def test_fresh_state_has_no_session_and_nothing_completed(tmp_path):
    state = RunState(state_path_for(tmp_path, "doc-a"))
    assert state.session_id is None
    assert state.is_completed("stage-1") is False


def test_session_id_persists_across_instances(tmp_path):
    path = state_path_for(tmp_path, "doc-a")
    RunState(path).set_session_id("sess-abc")
    reloaded = RunState(path)
    assert reloaded.session_id == "sess-abc"


def test_completed_items_persist_across_instances(tmp_path):
    path = state_path_for(tmp_path, "doc-a")
    state = RunState(path)
    state.mark_completed("stage-1")
    state.mark_completed("stage-2")

    reloaded = RunState(path)
    assert reloaded.is_completed("stage-1") is True
    assert reloaded.is_completed("stage-2") is True
    assert reloaded.is_completed("stage-3") is False


def test_marking_completed_survives_a_simulated_crash_between_items(tmp_path):
    """The actual crash-safety claim: mark_completed saves to disk
    immediately, not just at the end of a run — so a process that dies
    after item 2 of 5 doesn't lose the fact that items 1-2 succeeded."""
    path = state_path_for(tmp_path, "doc-a")
    state = RunState(path)
    state.mark_completed("stage-1")
    state.mark_completed("stage-2")
    # Simulate a crash right here — no further code runs, process just
    # "dies." A fresh RunState reading the same file is what a restarted
    # process would see.
    survivor = RunState(path)
    assert survivor.is_completed("stage-1") is True
    assert survivor.is_completed("stage-2") is True
    assert survivor.is_completed("stage-3") is False


def test_different_stable_keys_get_different_state_files(tmp_path):
    path_a = state_path_for(tmp_path, "doc-a")
    path_b = state_path_for(tmp_path, "doc-b")
    assert path_a != path_b


def test_same_stable_key_always_maps_to_same_path(tmp_path):
    assert state_path_for(tmp_path, "doc-a") == state_path_for(tmp_path, "doc-a")


def test_reset_clears_state_and_removes_file(tmp_path):
    path = state_path_for(tmp_path, "doc-a")
    state = RunState(path)
    state.mark_completed("stage-1")
    assert path.exists()

    state.reset()
    assert state.is_completed("stage-1") is False
    assert not path.exists()


def test_run_lock_can_be_acquired_and_released(tmp_path):
    state = RunState(state_path_for(tmp_path, "doc-a"))
    state.acquire_lock()
    state.mark_completed("stage-1")
    state.release_lock()
    assert RunState(state.state_path).is_completed("stage-1") is True