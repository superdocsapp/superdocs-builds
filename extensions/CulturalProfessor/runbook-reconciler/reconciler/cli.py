"""The command line.

Subcommands are registered in `COMMANDS` and land stage by stage; a command
appears here when it works, so `./rr --help` never advertises something that
answers "not implemented yet".

Every command that can spend a paid operation says so in its own help text.
The default is that nothing spends: `check` and `report` are local and free,
and only `sweep --apply` reaches the SuperDocs API at all.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from reconciler import __version__

Handler = Callable[[argparse.Namespace], int]


def _cmd_version(_: argparse.Namespace) -> int:
    print(f"runbook-reconciler {__version__}")
    return 0


COMMANDS: dict[str, tuple[str, Handler]] = {
    "version": ("print the version and exit", _cmd_version),
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rr",
        description=(
            "Check operational runbooks against the infrastructure they describe. "
            "Reads DevOps files, writes documents; never the other way round."
        ),
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    for name, (help_text, handler) in COMMANDS.items():
        child = sub.add_parser(name, help=help_text, description=help_text)
        child.set_defaults(handler=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler: Handler | None = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
