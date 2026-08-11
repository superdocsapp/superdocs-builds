"""Tests for choosing which documents a run looks at.

Only touched documents are checked - that is the card's speed requirement, and it is implemented
here rather than by checking everything quickly.
"""

from __future__ import annotations

import subprocess

import pytest

from docs_lint.config import Config, parse_config
from docs_lint.targets import GitUnavailable, select_targets


def repo(tmp_path, files: dict[str, str]):
    for name, body in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return Config(root=tmp_path)


def names(targets) -> list[str]:
    return [t.relative for t in targets]


# -- explicit paths, which is what pre-commit passes --------------------------------


def test_explicit_paths_are_checked_and_nothing_else(tmp_path):
    config = repo(tmp_path, {"a.md": "# A\n", "b.md": "# B\n", "c.md": "# C\n"})
    targets, _ = select_targets(config, paths=[str(tmp_path / "a.md")])
    assert names(targets) == ["a.md"]


def test_the_file_is_read_once_and_carried_with_the_target(tmp_path):
    config = repo(tmp_path, {"a.md": "# Hello\n"})
    targets, _ = select_targets(config, paths=["a.md"])
    assert targets[0].text == "# Hello\n"
    assert targets[0].data == b"# Hello\n"


def test_relative_and_absolute_paths_both_work(tmp_path):
    config = repo(tmp_path, {"docs/a.md": "# A\n"})
    relative, _ = select_targets(config, paths=["docs/a.md"])
    absolute, _ = select_targets(config, paths=[str(tmp_path / "docs" / "a.md")])
    assert names(relative) == names(absolute) == ["docs/a.md"]


# -- filtering ----------------------------------------------------------------------


def test_non_markdown_files_are_ignored_even_when_named_explicitly(tmp_path):
    config = repo(tmp_path, {"a.md": "# A\n", "script.py": "x = 1\n", "notes.txt": "hi\n"})
    targets, _ = select_targets(config, paths=["a.md", "script.py", "notes.txt"])
    assert names(targets) == ["a.md"]


def test_mdx_is_in_scope(tmp_path):
    config = repo(tmp_path, {"page.mdx": "# Page\n"})
    targets, _ = select_targets(config, paths=["page.mdx"])
    assert names(targets) == ["page.mdx"]


def test_dependency_directories_are_excluded_by_default(tmp_path):
    config = repo(
        tmp_path,
        {"a.md": "# A\n", "node_modules/pkg/readme.md": "# dep\n", ".venv/lib/doc.md": "# venv\n"},
    )
    targets, _ = select_targets(config)
    assert names(targets) == ["a.md"]


def test_a_top_level_excluded_directory_is_also_matched(tmp_path):
    """`**/node_modules/**` must exclude a top-level node_modules, not only a nested one."""
    config = repo(tmp_path, {"node_modules/readme.md": "# dep\n"})
    targets, _ = select_targets(config)
    assert names(targets) == []


def test_custom_excludes_are_honoured(tmp_path):
    repo(tmp_path, {"a.md": "# A\n", "CHANGELOG.md": "# changes\n"})
    config = parse_config({"docs-lint": {"exclude": ["CHANGELOG.md"]}}, root=tmp_path)
    targets, _ = select_targets(config)
    assert names(targets) == ["a.md"]


def test_a_missing_file_is_skipped_rather_than_fatal(tmp_path):
    config = repo(tmp_path, {"a.md": "# A\n"})
    targets, _ = select_targets(config, paths=["a.md", "gone.md"])
    assert names(targets) == ["a.md"]


def test_results_are_sorted_and_deduplicated(tmp_path):
    config = repo(tmp_path, {"b.md": "# B\n", "a.md": "# A\n"})
    targets, _ = select_targets(config, paths=["b.md", "a.md", "b.md"])
    assert names(targets) == ["a.md", "b.md"]


# -- sample mode --------------------------------------------------------------------


def test_sample_mode_limits_the_run_and_says_what_it_skipped(tmp_path):
    """Skipping work quietly is how a linter reports a clean repository it never read."""
    config = repo(tmp_path, {f"doc{i}.md": "# doc\n" for i in range(5)})
    targets, notes = select_targets(config, limit=2)

    assert len(targets) == 2
    assert any("2 of 5" in note and "3 not checked" in note for note in notes)


def test_no_limit_checks_everything(tmp_path):
    config = repo(tmp_path, {f"doc{i}.md": "# doc\n" for i in range(4)})
    targets, notes = select_targets(config, limit=0)
    assert len(targets) == 4
    assert notes == []


# -- git ----------------------------------------------------------------------------


def git_repo(tmp_path):
    def run(*args):
        subprocess.run(
            ["git", "-C", str(tmp_path), *args], check=True, capture_output=True, text=True
        )

    run("init", "-b", "main")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    return run


def test_since_selects_only_files_changed_against_a_ref(tmp_path):
    run = git_repo(tmp_path)
    (tmp_path / "old.md").write_text("# Old\n")
    run("add", "-A")
    run("commit", "-m", "first")

    (tmp_path / "new.md").write_text("# New\n")
    (tmp_path / "old.md").write_text("# Old\n\nEdited.\n")
    run("add", "-A")

    config = Config(root=tmp_path)
    targets, notes = select_targets(config, since="HEAD")
    assert set(names(targets)) == {"new.md", "old.md"}
    assert any("HEAD" in note for note in notes)


def test_since_ignores_files_that_did_not_change(tmp_path):
    run = git_repo(tmp_path)
    (tmp_path / "untouched.md").write_text("# Untouched\n")
    (tmp_path / "touched.md").write_text("# Touched\n")
    run("add", "-A")
    run("commit", "-m", "first")

    (tmp_path / "touched.md").write_text("# Touched\n\nEdited.\n")

    targets, _ = select_targets(Config(root=tmp_path), since="HEAD")
    assert names(targets) == ["touched.md"]


def test_a_deleted_file_is_not_linted(tmp_path):
    run = git_repo(tmp_path)
    (tmp_path / "doomed.md").write_text("# Doomed\n")
    run("add", "-A")
    run("commit", "-m", "first")
    (tmp_path / "doomed.md").unlink()
    run("add", "-A")

    targets, _ = select_targets(Config(root=tmp_path), since="HEAD")
    assert names(targets) == []


def test_since_outside_a_git_repository_says_so_plainly(tmp_path):
    with pytest.raises(GitUnavailable, match="not a git repository"):
        select_targets(Config(root=tmp_path), since="HEAD")
