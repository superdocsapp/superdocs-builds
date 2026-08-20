"""Fact tables, and the three places a baseline can come from."""

from __future__ import annotations

from pathlib import Path

import pytest

from docsync.facts import (
    DirectoryTree,
    GitRevisionTree,
    SourceError,
    WorkingTree,
    is_dirty,
    is_git_repo,
    read_facts,
    table_from_snapshot,
)
from docsync.registry import Registry
from tests.conftest import edit_file


class TestWorkingTree:
    def test_reads_every_declared_fact(self, repo: Path):
        table = read_facts(Registry.load(repo), WorkingTree(repo))
        assert table.errors == {}
        assert table["retry.max_attempts"].text == "3"
        assert table["retry.backoff_seconds"].text == "30 seconds"
        assert table["sla.uptime_target"].text == "99.95%"
        assert table["api.endpoints"].text == [
            "GET /v1/circuits",
            "GET /v1/circuits/{circuit_id}",
            "POST /v1/circuits",
            "POST /v1/circuits/{circuit_id}/provision",
        ]

    def test_one_broken_fact_does_not_hide_the_others(self, repo: Path):
        # A caller needs the whole picture to decide whether to stop, so a bad
        # extractor is recorded against its own fact rather than raising.
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = compute()")
        table = read_facts(Registry.load(repo), WorkingTree(repo))
        assert "retry.max_attempts" in table.errors
        assert table["retry.backoff_seconds"].text == "30 seconds"
        assert not table["retry.max_attempts"].ok
        assert "unresolved" in table["retry.max_attempts"].display

    def test_a_missing_source_file_is_reported_per_fact(self, repo: Path):
        (repo / "service.json").unlink()
        table = read_facts(Registry.load(repo), WorkingTree(repo))
        assert "sla.uptime_target" in table.errors
        assert "not present" in table.errors["sla.uptime_target"]

    def test_snapshot_omits_unresolved_facts(self, repo: Path):
        # A null baseline would make the next run report a fabricated change
        # from nothing to something.
        edit_file(repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = compute()")
        snapshot = read_facts(Registry.load(repo), WorkingTree(repo)).as_snapshot()
        assert "retry.max_attempts" not in snapshot
        assert snapshot["retry.backoff_seconds"] == "30 seconds"


class TestGitRevision:
    def test_reads_files_as_they_were(self, git_repo: Path, git):
        edit_file(git_repo, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 9")
        registry = Registry.load(git_repo)

        now = read_facts(registry, WorkingTree(git_repo))
        before = read_facts(registry, GitRevisionTree(git_repo, "HEAD"))
        assert now["retry.max_attempts"].text == "9"
        assert before["retry.max_attempts"].text == "3"

    def test_names_the_revision_it_resolved(self, git_repo: Path):
        tree = GitRevisionTree(git_repo, "main")
        assert tree.name.startswith("revision main (")

    def test_an_unknown_revision_fails_clearly(self, git_repo: Path):
        with pytest.raises(SourceError, match="not a commit"):
            GitRevisionTree(git_repo, "no-such-branch")

    def test_resolves_paths_when_the_registry_is_below_the_repo_root(
        self, tmp_path: Path, git, repo: Path
    ):
        # git show wants a path relative to the repository root, and the
        # registry usually sits below it. Getting the prefix wrong reports
        # "not present at revision" for every fact, which reads exactly like a
        # legitimate "these are all new" — a wrong answer that looks right.
        outer = tmp_path / "monorepo"
        outer.mkdir()
        nested = outer / "services" / "provisioning"
        nested.parent.mkdir(parents=True)
        repo.rename(nested)
        git(outer, "init", "-q", "-b", "main")
        git(outer, "config", "user.email", "t@example.invalid")
        git(outer, "config", "user.name", "t")
        git(outer, "add", "-A")
        git(outer, "commit", "-q", "-m", "initial")

        edit_file(nested, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 9")
        registry = Registry.load(nested)
        before = read_facts(registry, GitRevisionTree(nested, "HEAD"))
        assert before.errors == {}
        assert before["retry.max_attempts"].text == "3"

    def test_a_file_absent_at_the_revision_is_an_error_not_a_silent_empty(
        self, git_repo: Path
    ):
        registry = Registry.load(git_repo)
        (git_repo / "src" / "provisioning" / "new.py").write_text("NEW = 1\n")
        registry.facts["new.thing"] = registry.facts["retry.max_attempts"].__class__(
            key="new.thing", label="New thing", source="src/provisioning/new.py",
            kind="python_constant", argument="NEW",
        )
        before = read_facts(registry, GitRevisionTree(git_repo, "HEAD"))
        assert "new.thing" in before.errors


class TestDirtyDetection:
    def test_clean_file_is_clean(self, git_repo: Path):
        assert is_git_repo(git_repo)
        assert not is_dirty(git_repo, "docs/sla-summary.md")

    def test_modified_file_is_dirty(self, git_repo: Path):
        edit_file(git_repo, "docs/sla-summary.md", "99.95%", "99.99%")
        assert is_dirty(git_repo, "docs/sla-summary.md")

    def test_untracked_file_counts_as_dirty(self, git_repo: Path):
        # Overwriting an untracked document destroys it with no way back, which
        # is worse than the tracked case rather than better.
        (git_repo / "docs" / "new.md").write_text("---\ndocsync:\n  covers: []\n---\n")
        assert is_dirty(git_repo, "docs/new.md")

    def test_outside_a_repository_everything_is_treated_as_dirty(self, repo: Path):
        assert not is_git_repo(repo)
        assert is_dirty(repo, "docs/sla-summary.md")


class TestSnapshotTable:
    def test_round_trips(self, repo: Path):
        registry = Registry.load(repo)
        snapshot = read_facts(registry, WorkingTree(repo)).as_snapshot()
        rebuilt = table_from_snapshot(registry, snapshot)
        assert rebuilt["retry.backoff_seconds"].text == "30 seconds"
        assert rebuilt["api.endpoints"].is_list
        assert rebuilt.errors == {}

    def test_a_fact_added_since_the_snapshot_is_flagged_not_invented(self, repo: Path):
        registry = Registry.load(repo)
        snapshot = read_facts(registry, WorkingTree(repo)).as_snapshot()
        snapshot.pop("sla.uptime_target")
        rebuilt = table_from_snapshot(registry, snapshot)
        assert "sla.uptime_target" in rebuilt.errors
        assert "added to the" in rebuilt.errors["sla.uptime_target"]


class TestDirectoryTree:
    def test_compares_two_checkouts(self, repo: Path, tmp_path: Path):
        import shutil

        other = tmp_path / "other"
        shutil.copytree(repo, other)
        edit_file(other, "src/provisioning/retry.py", "MAX_ATTEMPTS = 3", "MAX_ATTEMPTS = 7")
        table = read_facts(Registry.load(repo), DirectoryTree(other))
        assert table["retry.max_attempts"].text == "7"
