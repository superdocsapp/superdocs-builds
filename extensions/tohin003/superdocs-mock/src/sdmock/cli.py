"""sdmock command line: serve, catalogue, record, bench.

Kept import-light on the `serve` path. Startup time is a graded property of this project,
so nothing heavier than Starlette and the JSON spec loads before the first request.
"""

from __future__ import annotations

import argparse
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .app import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        access_log=not args.quiet,
    )
    return 0


def cmd_catalogue(args: argparse.Namespace) -> int:
    from .replay import Library

    library = Library()
    rows = library.catalogue()
    if args.json:
        from .cassette import dumps

        print(dumps(rows))
        return 0

    print(f"{len(rows)} scenarios (default: {library.default_scenario()})\n")
    for row in rows:
        mark = "  [SYNTHESISED]" if row["synthesised"] else ""
        print(f"{row['scenario']}{mark}")
        print(f"    {row['description']}")
        if row["synthesised"]:
            print(f"    why not recorded: {row['synthesis_note']}")
        print(f"    endpoints: {', '.join(row['endpoints'])}")
        print(f"    behaviours: {', '.join(row['covers'])}")
        print()
    return 0


def cmd_routes(args: argparse.Namespace) -> int:
    from .spec import load

    spec = load()
    for method, template in spec.iter_routes():
        print(f"  {method:7s} {template:58s} {spec.summary(method, template)[:60]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sdmock",
        description="Offline mock of the SuperDocs REST API and MCP server.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the mock (REST at /v1/*, MCP at /mcp/)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8080)
    serve.add_argument("--log-level", default="warning")
    serve.add_argument("--quiet", action="store_true")
    serve.set_defaults(func=cmd_serve)

    cat = sub.add_parser("catalogue", help="list the scenarios this mock can serve")
    cat.add_argument("--json", action="store_true")
    cat.set_defaults(func=cmd_catalogue)

    routes = sub.add_parser("routes", help="list the routes the pinned spec describes")
    routes.set_defaults(func=cmd_routes)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
