"""Preflight tests: the run must refuse to start when H3 determinism would be
unverifiable after the fact.

These use a run directory inside the repository, under `runs/`, because that is
where a real run directory lives — the publication check asks git whether the
path is tracked, and a pytest tmp_path outside the work tree cannot answer that
question. Testing the check somewhere git cannot see it would validate a
configuration the experiment never uses.
"""

from __future__ import annotations

import json
import shutil

import pytest

from runner.preflight import (ROOT, PreflightError, cache_path_for,
                              check_h3_cache_is_published, pin_versions,
                              run_preflight)

VERSIONS = {"rubric": "1.0.3", "templates": "1.0.1", "prompt": "seed_draft_v2"}


@pytest.fixture
def run_dir(request):
    """A run directory in its real location, removed afterwards."""
    path = ROOT / "runs" / f"_pytest_{request.node.name[:40]}"
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _with_cache(path, cache: dict):
    cache_path_for(path).write_text(json.dumps(cache))
    return path


def test_missing_cache_aborts_the_run(run_dir):
    with pytest.raises(PreflightError, match="h3_cache_exists"):
        run_preflight(run_dir, arm_index=0, versions=VERSIONS)


def test_unparseable_cache_aborts_the_run(run_dir):
    cache_path_for(run_dir).write_text("{not json")
    with pytest.raises(PreflightError, match="does not parse"):
        run_preflight(run_dir, arm_index=0, versions=VERSIONS)


def test_first_arm_may_start_with_an_empty_cache(run_dir):
    """A fresh experiment legitimately has nothing cached yet."""
    results = run_preflight(_with_cache(run_dir, {}), arm_index=0,
                            versions=VERSIONS)
    assert all(r.ok for r in results), [str(r) for r in results if not r.ok]


def test_second_arm_refuses_to_start_on_an_empty_cache(run_dir):
    """This is the check that actually protects the cross-arm guarantee."""
    with pytest.raises(PreflightError, match="empty at arm 1"):
        run_preflight(_with_cache(run_dir, {}), arm_index=1, versions=VERSIONS)


def test_second_arm_starts_when_the_cache_is_warm(run_dir):
    _with_cache(run_dir, {"abc123": {"count": 1, "clauses": []}})
    assert all(r.ok for r in run_preflight(run_dir, arm_index=1,
                                           versions=VERSIONS))


def test_cache_outside_the_run_directory_is_rejected(run_dir, tmp_path):
    stray = tmp_path / "h3_cache.json"
    stray.write_text("{}")
    cache_path_for(run_dir).symlink_to(stray)
    with pytest.raises(PreflightError, match="outside the run directory"):
        run_preflight(run_dir, arm_index=0, versions=VERSIONS)


def test_git_ignored_cache_location_is_rejected():
    """A cache git will not track cannot be published with the raw data."""
    path = ROOT / ".state" / "preflight_probe"   # .state/ is gitignored
    path.mkdir(parents=True, exist_ok=True)
    cache_path_for(path).write_text("{}")
    try:
        result = check_h3_cache_is_published(path)
        assert not result.ok
        assert "git-ignored" in result.detail
    finally:
        shutil.rmtree(ROOT / ".state" / "preflight_probe", ignore_errors=True)


def test_publication_check_degrades_closed_when_git_cannot_answer(
        run_dir, monkeypatch):
    """'I could not tell' must fail, not pass. A precondition that degrades
    open is exactly how an unverifiable experiment gets produced."""
    import runner.preflight as pf
    _with_cache(run_dir, {"a": {}})
    monkeypatch.setattr(pf, "_git_ignore_status", lambda path: "unknown")
    result = pf.check_h3_cache_is_published(run_dir)
    assert not result.ok
    assert "degrades closed" in result.detail


def test_version_drift_mid_experiment_aborts_the_run(run_dir):
    _with_cache(run_dir, {"a": {}})
    run_preflight(run_dir, arm_index=0, versions=VERSIONS)
    pin_versions(run_dir, VERSIONS, arm_index=0)
    with pytest.raises(PreflightError, match="versions changed mid-experiment"):
        run_preflight(run_dir, arm_index=1,
                      versions=dict(VERSIONS, rubric="1.1.0"))


def test_preflight_reports_every_failure_not_just_the_first(run_dir):
    results = run_preflight(run_dir, arm_index=1, versions=VERSIONS,
                            raise_on_failure=False)
    failed = {r.name for r in results if not r.ok}
    assert {"h3_cache_exists", "h3_cache_non_empty"} <= failed


def test_corpus_check_counts_the_committed_documents(run_dir):
    _with_cache(run_dir, {"a": {}})
    results = run_preflight(run_dir, arm_index=0, versions=VERSIONS)
    corpus = next(r for r in results if r.name == "corpus_present")
    assert corpus.ok and "20 documents" in corpus.detail


def test_wrong_document_count_aborts_the_run(run_dir):
    _with_cache(run_dir, {"a": {}})
    with pytest.raises(PreflightError, match="expected 21 documents"):
        run_preflight(run_dir, arm_index=0, versions=VERSIONS,
                      expected_documents=21)
