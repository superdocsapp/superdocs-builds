"""
Thin wrapper around git for real usage. Deliberately isolated in its own module -- code_diff.py and
sync_engine.py never call subprocess directly, so their tests (and any future non-git integration, e.g. a
CI system that already has before/after content) never need a real git repo.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass
class ChangedFile:
    path: str
    old_content: str  # "" if the file is newly added
    new_content: str  # "" if the file was deleted


def _run(args: list[str], cwd: str) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0 and "does not exist" not in result.stderr:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
    return result.stdout


def get_changed_python_files(repo_path: str, against: str = "HEAD") -> list[ChangedFile]:
    """Returns every changed .py file between the working tree and `against` (default: last commit), with
    both old and new full-file content -- code_diff.py needs full files, not diff hunks, to build an
    accurate AST-level comparison."""
    names_output = _run(["diff", "--name-only", against], cwd=repo_path)
    changed_paths = [p for p in names_output.splitlines() if p.strip().endswith(".py")]

    changed_files = []
    for path in changed_paths:
        try:
            old_content = _run(["show", f"{against}:{path}"], cwd=repo_path)
        except RuntimeError:
            old_content = ""  # newly added file, no old version

        try:
            with open(f"{repo_path}/{path}", "r", encoding="utf-8") as f:
                new_content = f.read()
        except FileNotFoundError:
            new_content = ""  # deleted file, no new version

        changed_files.append(ChangedFile(path=path, old_content=old_content, new_content=new_content))

    return changed_files
