# Operator commands. `audit verify` is the one that matters: a tamper-evident
# log nobody can check is just a log.

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from gateway.audit import read_entries, verify_chain
from gateway.policy import hash_token
from gateway.settings import get_settings


def _cmd_audit_verify(args: argparse.Namespace) -> int:
    result = verify_chain(args.path)
    print(result.describe())
    if not result.ok:
        print(f"\n  log:  {args.path}", file=sys.stderr)
        print("  Entries before the break are still trustworthy;", file=sys.stderr)
        print("  everything from that line on must be treated as unverified.", file=sys.stderr)
        return 1
    return 0


def _cmd_audit_tail(args: argparse.Namespace) -> int:
    entries = [e for _, e in read_entries(args.path)]
    for entry in entries[-args.number :]:
        print(json.dumps(entry, indent=2 if args.pretty else None, sort_keys=True))
    return 0


def _cmd_audit_stats(args: argparse.Namespace) -> int:
    decisions: Counter[str] = Counter()
    billed: Counter[str] = Counter()
    total = 0

    for _, entry in read_entries(args.path):
        total += 1
        decisions[str(entry.get("decision", "?"))] += 1
        team = entry.get("team")
        if team:
            billed[str(team)] += int(entry.get("billed", 0) or 0)

    if total == 0:
        print(f"no entries in {args.path}")
        return 0

    print(f"{total} entries in {args.path}\n")
    print("by decision:")
    for name, count in decisions.most_common():
        print(f"  {name:<22} {count:>6}")
    if billed:
        print("\nbilled units by team:")
        for name, count in billed.most_common():
            print(f"  {name:<22} {count:>6}")
    return 0


def _cmd_hash_token(args: argparse.Namespace) -> int:
    # So an operator can populate policy.yml without ever writing the token
    # itself into a file that gets committed.
    print(hash_token(args.token))
    return 0


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="gateway", description="policy-gateway operator commands")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="inspect the audit log")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)

    def _add_path(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "path",
            nargs="?",
            default=settings.audit_log_path,
            help=f"path to the audit log (default: {settings.audit_log_path})",
        )

    verify = audit_sub.add_parser("verify", help="walk the hash chain, report the first break")
    _add_path(verify)
    verify.set_defaults(func=_cmd_audit_verify)

    tail = audit_sub.add_parser("tail", help="print the most recent entries")
    _add_path(tail)
    tail.add_argument("-n", "--number", type=int, default=10, help="entries to show (default: 10)")
    tail.add_argument("--pretty", action="store_true", help="indent the JSON")
    tail.set_defaults(func=_cmd_audit_tail)

    stats = audit_sub.add_parser("stats", help="summarise decisions and billed units")
    _add_path(stats)
    stats.set_defaults(func=_cmd_audit_stats)

    token = sub.add_parser("hash-token", help="hash a gateway token for policy.yml")
    token.add_argument("token")
    token.set_defaults(func=_cmd_hash_token)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
