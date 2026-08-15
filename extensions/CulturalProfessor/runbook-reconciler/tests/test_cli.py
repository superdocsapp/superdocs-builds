"""The command line's own contract.

Small on purpose. What is worth pinning here is that the entry point exists,
that every registered command is reachable, and that running `rr` with nothing
is a help page and a non-zero exit rather than a traceback — the first thing a
stranger does is run it with no arguments, and that first impression is part of
the product.
"""

from __future__ import annotations

import pytest

from reconciler.cli import COMMANDS, build_parser, main


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
