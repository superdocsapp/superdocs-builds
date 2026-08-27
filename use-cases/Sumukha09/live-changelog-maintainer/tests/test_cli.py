"""CLI smoke tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "changelog.py", *args],
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
    )


def test_cli_init_then_dry_run(tmp_path: Path):
    repo = Path(__file__).resolve().parent.parent
    state = tmp_path / "state.json"
    release = tmp_path / "release.json"
    release.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "date": "2026-01-01",
                "sections": {"Added": [{"text": "Hello"}]},
            }
        )
    )

    # init (no remote creation)
    result = _run(
        "init",
        "--title",
        "Changelog",
        "--owner",
        "me",
        "--repo",
        "cool",
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        "--local-only",
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert state.exists()

    # preview
    result = _run(
        "preview",
        str(release),
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert "[1.0.0] - 2026-01-01" in result.stdout

    # update with --dry-run
    result = _run(
        "update",
        str(release),
        "--dry-run",
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert "DRY-RUN" in result.stdout

    # verify
    result = _run(
        "verify",
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr

    # export md
    result = _run(
        "export",
        "--format",
        "md",
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "out" / "CHANGELOG.md").exists()


def test_cli_flags_before_subcommand(tmp_path: Path):
    repo = Path(__file__).resolve().parent.parent
    state = tmp_path / "state.json"

    # Flags before subcommand
    result = _run(
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        "init",
        "--title",
        "Test Docs",
        "--owner",
        "org",
        "--repo",
        "pkg",
        "--local-only",
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert state.exists()


def test_cli_custom_style_file(tmp_path: Path):
    repo = Path(__file__).resolve().parent.parent
    state = tmp_path / "state.json"
    style_file = tmp_path / "style.json"
    style_file.write_text(
        json.dumps(
            {
                "heading_level": 2,
                "title_format": "Version {version} ({date})",
                "bullet_marker": "*",
                "emoji_policy": "none",
                "section_heading_level": 3,
                "section_order": ["Added", "Fixed"],
                "include_comparison_link": False,
                "trailing_blank_lines": 2,
            }
        )
    )

    result = _run(
        "init",
        "--title",
        "Custom Style Docs",
        "--owner",
        "org",
        "--repo",
        "pkg",
        "--style-file",
        str(style_file),
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        "--local-only",
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert state.exists()

    release = tmp_path / "release.json"
    release.write_text(
        json.dumps(
            {
                "version": "1.0.0",
                "date": "2026-01-01",
                "sections": {"Added": [{"text": "First feature"}]},
            }
        )
    )

    result = _run(
        "preview",
        str(release),
        "--state",
        str(state),
        "--output-dir",
        str(tmp_path / "out"),
        cwd=repo,
    )
    assert result.returncode == 0, result.stderr
    assert "Version 1.0.0 (2026-01-01)" in result.stdout
    assert "* First feature" in result.stdout
