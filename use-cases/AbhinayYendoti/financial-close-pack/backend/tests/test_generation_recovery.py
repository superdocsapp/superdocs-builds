"""A crash during generation must not strand the close.

`generating` was only ever cleared by `run_generation`. If the worker died mid-run the
flag stayed set in sqlite, so every later attempt got 409 GENERATION_IN_PROGRESS and the
derived status stayed GENERATING forever. There was no recovery path of any kind, and
`store.active_job_for_close` - written for exactly this - was never called.
"""

from datetime import datetime, timedelta, timezone

from backend.app.core.config import settings
from backend.app.db import store


def _strand(close_id, *, minutes_ago):
    """Leave the close in the state a worker that died mid-generation would leave it."""
    began = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)

    def mutator(close):
        close["generating"] = True
        close["generating_since"] = began.isoformat()

    store.mutate_close(close_id, mutator)
    return began


def test_a_stranded_generation_flag_is_released(client, auth, ready_close):
    close_id = ready_close()["id"]
    _strand(close_id, minutes_ago=60)

    response = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth)
    assert response.status_code == 202

    job = response.json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"
    assert client.get(f"/api/v1/closes/{close_id}/reviews", headers=auth).json()


def test_a_stranded_close_does_not_report_itself_as_generating(client, auth, ready_close):
    close_id = ready_close()["id"]
    _strand(close_id, minutes_ago=60)

    assert client.get(f"/api/v1/closes/{close_id}", headers=auth).json()["status"] != "GENERATING"


def test_superseding_a_stranded_run_fails_its_orphaned_job(client, auth, ready_close):
    """The abandoned job row stayed RUNNING, so the UI would poll it forever."""
    close_id = ready_close()["id"]
    orphan = {
        "id": "job_orphaned",
        "close_id": close_id,
        "status": "RUNNING",
        "stage": "UPLOADING",
        "stage_index": 2,
        "stages": [],
        "attempt": 1,
        "error": None,
        "started_by": "Abhinay Reddy",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    store.save_job(orphan)
    _strand(close_id, minutes_ago=60)

    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 202

    superseded = client.get(f"/api/v1/closes/{close_id}/jobs/job_orphaned", headers=auth).json()
    assert superseded["status"] == "FAILED"
    assert superseded["error"] and superseded["completed_at"]

    trail = [entry["event"] for entry in client.get(f"/api/v1/closes/{close_id}/audit", headers=auth).json()]
    assert "GENERATION_ABANDONED" in trail


def test_a_generation_that_could_still_be_running_is_left_alone(client, auth, ready_close):
    """The fix must not turn the concurrency guard off; only expired flags are released."""
    close_id = ready_close()["id"]
    _strand(close_id, minutes_ago=1)

    response = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth)
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "GENERATION_IN_PROGRESS"
    assert client.get(f"/api/v1/closes/{close_id}", headers=auth).json()["status"] == "GENERATING"


def test_the_staleness_window_is_configurable(client, auth, ready_close, monkeypatch):
    close_id = ready_close()["id"]
    _strand(close_id, minutes_ago=5)
    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 409

    monkeypatch.setattr(settings, "generation_timeout_seconds", 60)
    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 202


def test_a_flag_with_no_start_time_is_treated_as_stranded(client, auth, ready_close):
    """Closes written before generating_since existed must not be locked out."""
    close_id = ready_close()["id"]

    def mutator(close):
        close["generating"] = True
        close.pop("generating_since", None)

    store.mutate_close(close_id, mutator)

    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 202


def test_a_finished_generation_clears_the_start_time(client, auth, ready_close):
    close_id = ready_close()["id"]
    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "SUCCEEDED"

    close = store.get_close(close_id)
    assert close["generating"] is False
    assert close["generating_since"] is None


def test_a_failed_generation_also_releases_the_close(client, auth, ready_close, monkeypatch):
    close_id = ready_close()["id"]
    monkeypatch.setattr(settings, "superdocs_mode", "live")
    monkeypatch.setattr(settings, "superdocs_api_key", "")

    job = client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).json()
    assert client.get(f"/api/v1/closes/{close_id}/jobs/{job['id']}", headers=auth).json()["status"] == "FAILED"

    close = store.get_close(close_id)
    assert close["generating"] is False
    assert close["generating_since"] is None

    monkeypatch.setattr(settings, "superdocs_mode", "mock")
    assert client.post(f"/api/v1/closes/{close_id}/generate", headers=auth).status_code == 202
