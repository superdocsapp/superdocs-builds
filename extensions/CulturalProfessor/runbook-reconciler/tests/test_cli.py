"""The command line's own contract.

Small on purpose. What is worth pinning here is that the entry point exists,
that every registered command is reachable, and that running `rr` with nothing
is a help page and a non-zero exit rather than a traceback — the first thing a
stranger does is run it with no arguments, and that first impression is part of
the product.

The one test here that is about *money* rather than about ergonomics is
`test_propose_without_yes_spends_nothing`. `rr propose` is the only command in
this project that can be charged for, and the property that it does nothing
until it is asked twice is worth an assertion rather than a docstring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from reconciler.cli import COMMANDS, build_parser, main


@pytest.fixture
def scratch_register(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A register per test. The project's own `register.db` is not a fixture."""
    path = tmp_path / "register.db"
    monkeypatch.setenv("RR_REGISTER", str(path))
    return path


def test_bare_invocation_prints_help_and_fails(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 1
    assert "COMMAND" in capsys.readouterr().out


def test_every_registered_command_parses() -> None:
    parser = build_parser()
    for name in COMMANDS:
        args = parser.parse_args([name])
        assert callable(args.handler)


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    from reconciler import __version__

    assert main(["version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_check_finds_the_planted_drift_and_exits_non_zero(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Non-zero on drift is what lets CI gate on it."""
    assert main(["check"]) == 1
    out = capsys.readouterr().out

    assert "alerts" in out
    assert "paid operations" in out


def test_check_exit_zero_never_blocks(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pre-commit nudge's whole contract: it reports and gets out of the way."""
    assert main(["check", "--exit-zero"]) == 0
    assert "findings" in capsys.readouterr().out


def test_status_on_an_empty_register_is_zeroes_not_a_traceback(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["status"]) == 0
    out = capsys.readouterr().out

    assert "0 claims" in out
    assert "awaiting review" in out


def test_status_reports_what_a_sweep_left_behind(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check"])
    capsys.readouterr()

    assert main(["status"]) == 0
    out = capsys.readouterr().out

    assert "awaiting review" in out
    assert "recent runs:" in out
    assert "0 operation(s)" in out


def test_propose_without_yes_spends_nothing(
    scratch_register: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Priced, not spent — and proved by there being no client to spend with.

    `SUPERDOCS_API_KEY` is cleared, so any code path that actually reached the
    service would fail rather than quietly succeeding against a real key that
    happened to be in the environment.
    """
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    main(["check"])
    capsys.readouterr()

    assert main(["propose"]) == 0
    out = capsys.readouterr().out

    assert "this will spend" in out
    assert "nothing spent" in out


def test_propose_with_yes_and_no_key_refuses_rather_than_half_running(
    scratch_register: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SUPERDOCS_API_KEY", "")
    main(["check"])
    capsys.readouterr()

    assert main(["propose", "--yes"]) == 2
    assert "SUPERDOCS_API_KEY is not set" in capsys.readouterr().err


def test_propose_on_a_clean_estate_says_so(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Rule 5's shape at the command line: nothing found, nothing offered."""
    assert main(["propose"]) == 0
    assert "nothing to propose" in capsys.readouterr().out


def test_sweep_narrowed_to_pages_reports_no_coverage_number(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The six-false-dead-links bug, pinned at the level a user meets it."""
    assert main(["sweep", "--pages", "1008"]) in (0, 1)
    out = capsys.readouterr().out

    assert "coverage: not computed" in out
    assert "dead links" not in out


def test_review_with_auto_reject_writes_nothing(
    scratch_register: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main(["check"])
    capsys.readouterr()

    assert main(["review", "--auto", "reject"]) == 0
    out = capsys.readouterr().out

    assert "0 passages updated" in out
