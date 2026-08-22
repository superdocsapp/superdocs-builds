"""
Uses a REAL temporary git repo (created and torn down per test) rather than mocking subprocess -- git's
exact CLI output format (diff --name-only, show ref:path) is exactly the kind of thing a mock would get
subtly wrong and never notice. This costs a bit of test speed for a lot of confidence.
"""
import subprocess
import tempfile
import shutil
from pathlib import Path

import pytest

from src.git_integration import get_changed_python_files


@pytest.fixture
def temp_repo():
    tmp_dir = tempfile.mkdtemp()
    subprocess.run(["git", "init", "-q"], cwd=tmp_dir, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_dir, check=True)

    (Path(tmp_dir) / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    subprocess.run(["git", "add", "."], cwd=tmp_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=tmp_dir, check=True)

    yield tmp_dir
    shutil.rmtree(tmp_dir, ignore_errors=True)


def test_detects_a_modified_python_file(temp_repo):
    (Path(temp_repo) / "calc.py").write_text("def add(a, b, c=0):\n    return a + b + c\n")

    changed = get_changed_python_files(temp_repo)
    assert len(changed) == 1
    assert changed[0].path == "calc.py"
    assert "def add(a, b):" in changed[0].old_content
    assert "def add(a, b, c=0):" in changed[0].new_content


def test_ignores_non_python_files(temp_repo):
    (Path(temp_repo) / "notes.txt").write_text("some notes")
    changed = get_changed_python_files(temp_repo)
    assert changed == [], "non-.py file changes must not appear in the changed-files list"


def test_no_changes_returns_empty_list(temp_repo):
    changed = get_changed_python_files(temp_repo)
    assert changed == []


def test_newly_added_file_has_empty_old_content(temp_repo):
    (Path(temp_repo) / "new_module.py").write_text("def brand_new():\n    pass\n")
    subprocess.run(["git", "add", "new_module.py"], cwd=temp_repo, check=True)

    changed = get_changed_python_files(temp_repo)
    new_file = next(c for c in changed if c.path == "new_module.py")
    assert new_file.old_content == ""
    assert "brand_new" in new_file.new_content
