"""CLI entry point: python -m localizer run --countries IN [--limit N]."""

from __future__ import annotations

import argparse
import asyncio

from . import service
from .ledger import Ledger
from .packs import PackIntegrityError


def _parse_countries(value: str) -> list[str]:
    return [code.strip() for code in value.split(",") if code.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m localizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Lock the core and generate a pack per country.")
    run_parser.add_argument("--countries", required=True, help="Comma-separated country codes, e.g. IN,KE")
    run_parser.add_argument("--limit", type=int, default=None, help="Process only the first N countries.")

    repair_parser = subparsers.add_parser(
        "repair-pack-version",
        help=(
            "State repair only, never part of the normal flow: regenerate a "
            "country's pack against a prior core_version, for when state/out "
            "was lost or corrupted and the shipped pack no longer represents "
            "that version. Source-language countries regenerate against the "
            "archived master file (free); other languages regenerate against "
            "whatever is currently locked for that language at that version "
            "(must already exist — this command never translates on your "
            "behalf)."
        ),
    )
    repair_parser.add_argument("--countries", required=True, help="Comma-separated country codes")
    repair_parser.add_argument("--version", type=int, required=True, help="The core_version to regenerate against")

    args = parser.parse_args(argv)

    if args.command == "run":
        countries = _parse_countries(args.countries)
        outcome = asyncio.run(service.run(countries, limit=args.limit))
        for code, result in outcome["results"].items():
            status = "SKIPPED" if result.get("skipped") else "OK"
            print(f"[{code}] {status}")
        print()
        outcome["ledger"].report()
        return 0

    if args.command == "repair-pack-version":
        countries = _parse_countries(args.countries)
        ledger = Ledger.load()

        async def _repair_all() -> None:
            for code in countries:
                try:
                    result = await service.regenerate_pack_at_version(code, args.version, ledger=ledger)
                    status = "SKIPPED" if result.get("skipped") else "OK"
                    print(f"[{code}] {status}")
                except (ValueError, PackIntegrityError) as exc:
                    # One country's failure (e.g. still-flaky SuperDocs export,
                    # or no lock yet for its language) must not stop the rest
                    # of the batch from being attempted.
                    print(f"[{code}] FAILED: {exc}")

        asyncio.run(_repair_all())
        print()
        ledger.save()
        ledger.report()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
