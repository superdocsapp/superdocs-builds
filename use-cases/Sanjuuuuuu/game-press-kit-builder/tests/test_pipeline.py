import json
from pathlib import Path

from backend.pipeline import run_local

ROOT = Path(__file__).resolve().parent.parent


def test_pipeline_runs_on_emberfall_and_second_dataset(tmp_path):
    first_dir = tmp_path / "emberfall"
    first = run_local(str(ROOT / "sample-data/emberfall.json"), str(first_dir), str(ROOT / "sample-data/assets"))
    first_state = json.loads(first["state"].read_text())
    assert first["json"].exists()
    assert first["localized"].exists()
    assert "local_pipeline_complete" in first_state["completed_stages"]

    # A second invocation resumes from the saved state rather than requiring a live service.
    second_run = run_local(str(ROOT / "sample-data/emberfall.json"), str(first_dir), str(ROOT / "sample-data/assets"))
    assert second_run["json"].read_text() == first["json"].read_text()

    second = run_local(str(ROOT / "sample-data/ashvale.json"), str(tmp_path / "ashvale"), str(ROOT / "sample-data/assets"))
    assert second["json"].exists()
    assert "ashvale" in second["json"].name
