import json
import shutil
import tempfile
from pathlib import Path

import pytest

from benchmark.runner import run_benchmark, BudgetExceeded
from benchmark.client import ClientError, get_client


def test_mock_mode_full_run_no_network_needed():
    """The claim to verify: real tests exist and run without a live key."""
    tmp = Path(tempfile.mkdtemp())
    try:
        corpus_dir = tmp / "corpus"
        results_dir = tmp / "results"
        summary = run_benchmark(
            corpus_dir=corpus_dir,
            results_dir=results_dir,
            mode="mock",
            small_sample=True,
            repeats=1,
        )
        assert summary["num_edits"] > 0
        assert summary["mode"] == "mock"
        assert (results_dir / "raw_edits.csv").exists()
        assert (results_dir / "raw_edits.json").exists()
        assert (results_dir / "run_summary.json").exists()
    finally:
        shutil.rmtree(tmp)


def test_real_mode_without_api_key_fails_clearly():
    import os
    saved = os.environ.pop("SUPERDOCS_API_KEY", None)
    try:
        with pytest.raises(ClientError):
            get_client("real")
    finally:
        if saved is not None:
            os.environ["SUPERDOCS_API_KEY"] = saved


def test_both_arms_present_in_output():
    tmp = Path(tempfile.mkdtemp())
    try:
        corpus_dir = tmp / "corpus"
        results_dir = tmp / "results"
        run_benchmark(
            corpus_dir=corpus_dir,
            results_dir=results_dir,
            mode="mock",
            small_sample=True,
        )
        records = json.loads((results_dir / "raw_edits.json").read_text())
        arms = {r["arm"] for r in records}
        assert arms == {"whole_doc", "section_edit"}
    finally:
        shutil.rmtree(tmp)


def test_repeats_produce_multiple_labeled_runs():
    tmp = Path(tempfile.mkdtemp())
    try:
        corpus_dir = tmp / "corpus"
        results_dir = tmp / "results"
        run_benchmark(
            corpus_dir=corpus_dir,
            results_dir=results_dir,
            mode="mock",
            small_sample=True,
            repeats=3,
        )
        records = json.loads((results_dir / "raw_edits.json").read_text())
        repeat_prefixes = {r["task_id"].split("-")[0] for r in records}
        assert repeat_prefixes == {"r0", "r1", "r2"}
    finally:
        shutil.rmtree(tmp)


def test_stopping_rule_exists_and_run_summary_records_it():
    """Even in mock mode (which costs nothing) the run must have a defined
    stopping condition and report it — verifies the budget guard's bookkeeping
    path is exercised, per 'give anything that loops a clear stopping rule.'"""
    tmp = Path(tempfile.mkdtemp())
    try:
        corpus_dir = tmp / "corpus"
        results_dir = tmp / "results"
        summary = run_benchmark(
            corpus_dir=corpus_dir,
            results_dir=results_dir,
            mode="mock",
            small_sample=True,
        )
        assert "stopped_early" in summary
        assert summary["stopped_early"] is False  # mock mode has no budget cap
    finally:
        shutil.rmtree(tmp)
