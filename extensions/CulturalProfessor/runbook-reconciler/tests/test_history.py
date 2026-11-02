"""Attribution: which commit the drift arrived in.

Every test here that matters is about *failing soft*. The finding is already
actionable without a commit behind it, so a path outside a repository, an
uncommitted line, or a machine with no `git` on it must cost the attribution and
nothing else. A checker that refused to report drift because it could not work
out whose fault it was would have its priorities exactly backwards.

The tests run against this repository's own history, which is real: the fixture
estate is committed here, so `blame` has something true to find rather than a
mock that agrees with it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from reconciler.config import PROJECT_ROOT
from reconciler.history import Commit, _parse_porcelain, blame


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    """The blame cache is process-wide and these tests reuse paths."""
    from reconciler.history import _blame

    _blame.cache_clear()


def test_a_committed_evidence_line_names_its_commit() -> None:
    rules = PROJECT_ROOT / "fixtures/infra/platform-infra/monitoring/payments.rules.yml"
    commit = blame(rules, 6)

    assert commit is not None
    assert len(commit.sha) == 12
    assert commit.author
    assert commit.date.count("-") == 2, commit.date
    assert commit.describe().startswith(commit.sha[:7])


def test_the_same_line_twice_runs_git_once() -> None:
    """Three claims about one alert blame the same rules-file line three times,
    and the subprocess is by far the most expensive thing in the module."""
    rules = PROJECT_ROOT / "fixtures/infra/platform-infra/monitoring/payments.rules.yml"

    calls = 0
    real_run = subprocess.run

    def counting_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real_run(*args, **kwargs)

    subprocess.run = counting_run  # type: ignore[assignment]
    try:
        assert blame(rules, 6) == blame(rules, 6) != None  # noqa: E711
    finally:
        subprocess.run = real_run  # type: ignore[assignment]
    assert calls == 1


# ------------------------------------------------------------ failing soft --


def test_a_path_that_is_not_a_file_gets_no_attribution() -> None:
    assert blame(PROJECT_ROOT / "does-not-exist.yml", 3) is None
    assert blame(PROJECT_ROOT / "fixtures", 1) is None, "a directory is not a file"


def test_a_line_number_out_of_range_is_not_an_error() -> None:
    rules = PROJECT_ROOT / "fixtures/infra/platform-infra/monitoring/payments.rules.yml"
    assert blame(rules, 0) is None
    assert blame(rules, 999_999) is None


def test_a_file_outside_any_repository_gets_no_attribution(tmp_path: Path) -> None:
    loose = tmp_path / "payments.tf"
    loose.write_text('resource "aws_db_instance" "x" {}\n', encoding="utf-8")
    assert blame(loose, 1) is None


def test_an_uncommitted_line_is_not_attributed_to_a_commit(tmp_path: Path) -> None:
    """git reports all-zeroes for "not committed yet".

    Naming a commit for somebody's working tree would be inventing one.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    target = tmp_path / "rules.yml"
    target.write_text("threshold: 1.2\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "rules.yml"], check=True)

    assert blame(target, 1) is None


def test_git_being_absent_costs_the_attribution_and_nothing_else() -> None:
    rules = PROJECT_ROOT / "fixtures/infra/platform-infra/monitoring/payments.rules.yml"

    def no_git(*args, **kwargs):
        raise FileNotFoundError("git: command not found")

    real_run = subprocess.run
    subprocess.run = no_git  # type: ignore[assignment]
    try:
        assert blame(rules, 6) is None
    finally:
        subprocess.run = real_run  # type: ignore[assignment]


# ---------------------------------------------------------------- parsing --


def test_an_author_whose_name_contains_brackets_survives() -> None:
    """Which is why this reads porcelain and not `git blame`'s human output.

    The default format puts author and date in one parenthesised field with no
    delimiter a name cannot contain, and `Ana (Ana) Ruiz` is enough to break it.
    """
    porcelain = (
        "9f56935d782e14aa1 12 12 1\n"
        "author Ana (Ana) Ruiz\n"
        "author-time 1772409600\n"
        "author-tz +0000\n"
        "summary consolidate the rollback jobs\n"
        "filename deploy.yml\n"
        "\tmanual-rollback:\n"
    )
    commit = _parse_porcelain(porcelain)

    assert commit == Commit(
        sha="9f56935d782e",
        author="Ana (Ana) Ruiz",
        date="2026-03-02",
        subject="consolidate the rollback jobs",
    )


def test_an_unparseable_timestamp_loses_the_date_and_keeps_the_commit() -> None:
    commit = _parse_porcelain(
        "abc123def4567 1 1 1\nauthor Someone\nauthor-time not-a-number\nsummary x\n\tline\n"
    )
    assert commit is not None
    assert commit.date == ""
    assert commit.author == "Someone"
