"""Command line surface for the native Python doctor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import VERSION
from .core import load_contract, platform_name, scan
from .repair import repair


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="mcp-doctor", description="Diagnose SuperDocs MCP client configuration")
    result.add_argument("--client", help="restrict to one supported client")
    result.add_argument("--config", type=Path, help="diagnose one specific file")
    result.add_argument("--key-env", default=os.environ.get("MCP_DOCTOR_KEY_ENV", "SUPERDOCS_API_KEY"))
    result.add_argument("--json", action="store_true", help="machine-readable findings")
    result.add_argument("--report", action="store_true", help="redacted Markdown support report")
    result.add_argument("--fix", action="store_true", help="back up, repair what is sanctioned, and re-check")
    result.add_argument("--version", action="version", version=VERSION)
    return result


def text_report(report: dict) -> str:
    present = [client for client in report["clients"] if any(file["status"] != "absent" for file in client["config_files"])]
    if not present:
        return "No MCP client configuration found.\n  Looked for: " + ", ".join(client["name"] for client in report["clients"])
    lines: list[str] = []
    for client in present:
        own = [item for item in report["findings"] if item.get("client") == client["name"]]
        files = [file for file in client["config_files"] if file["status"] != "absent"]
        lines.append(f"{client['name']}: configuration looks correct" if not own else client["name"])
        for file in files:
            entries = len(file.get("entries", []))
            lines.append(f"  {file['path']} ({file['format']}, {entries} SuperDocs entr{'y' if entries == 1 else 'ies'})")
        if client.get("evidence_tier") != "captured":
            lines.append(f"  client knowledge: {client['evidence_tier']}")
        for finding in own:
            mark = {"error": "✗", "warn": "!", "info": "i"}[finding["severity"]]
            lines.append(f"  {mark} {finding['message']}")
            if finding.get("remediation"):
                lines.append(f"      → {finding['remediation']}")
        lines.append("")
    errors, warnings = report["summary"]["errors"], report["summary"]["warnings"]
    if errors == warnings == 0:
        lines.append("Nothing to report.")
    else:
        labels = ([f"{errors} error{'s' if errors != 1 else ''}"] if errors else []) + ([f"{warnings} warning{'s' if warnings != 1 else ''}"] if warnings else [])
        lines.append(", ".join(labels))
    if any(finding.get("auto_fixable") for finding in report["findings"]) and not any(client["write_capable"] for client in report["clients"]):
        lines.append("Automatic repair is not available yet; these must be corrected by hand.")
    unproven = [client["name"] for client in present if client.get("evidence_tier") != "captured"]
    if unproven:
        lines.append("Read-only and experimental for: " + ", ".join(unproven) + " (client knowledge not yet captured from a real install).")
    return "\n".join(lines).rstrip()


def markdown_report(report: dict) -> str:
    lines = ["# mcp-doctor report", "", f"- tool: {report['tool']['name']} {report['tool']['version']} ({report['tool']['implementation']})", f"- clients scanned: {report['summary']['clients_scanned']}", f"- files read: {report['summary']['config_files_read']}", f"- errors: {report['summary']['errors']}, warnings: {report['summary']['warnings']}", ""]
    for client in report["clients"]:
        files = [file for file in client["config_files"] if file["status"] != "absent"]
        if not files:
            continue
        lines.extend([f"## {client['name']}", "", f"- client knowledge: {client['evidence_tier']}", f"- write capable: {'yes' if client['write_capable'] else 'no'}"])
        lines.extend(f"- `{file['path']}` — {file['format']}, {file['status']}" for file in files)
        own = [finding for finding in report["findings"] if finding.get("client") == client["name"]]
        if own:
            lines.append("")
            lines.extend(f"- **{finding['severity']}** `{finding['id']}` — {finding['message']}" for finding in own)
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os_name = platform_name()
    if not os_name:
        print(f"unsupported platform: {sys.platform}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    contract = load_contract(env=env)
    if args.client and not any(client["id"] == args.client for client in contract.clients):
        print(f"unknown client '{args.client}'. Known: {', '.join(client['id'] for client in contract.clients)}", file=sys.stderr)
        return 2
    target = args.config.resolve() if args.config else None
    client = args.client
    if target and not client:
        guesses = [item["id"] for item in contract.clients if any(target.name == item_location["path"].split("/")[-1] for item_location in item["locations"])]
        if len(guesses) != 1:
            print("cannot tell which client this config belongs to; pass --client as well", file=sys.stderr)
            return 2
        client = guesses[0]
    report = scan(contract, cwd=Path.cwd(), env=env, os_name=os_name, client_filter=client, single_file=target, key_env=args.key_env, deterministic=env.get("MCP_DOCTOR_DETERMINISTIC") == "1")
    if args.client:
        selected = report["clients"][0] if report["clients"] else None
        present = selected and any(file["status"] != "absent" for file in selected["config_files"])
        has_entry = selected and any(file.get("entries") for file in selected["config_files"])
        if not present or not has_entry:
            report["exit_code"] = 1
    if args.fix:
        report, repair_lines, code = repair(contract, cwd=Path.cwd(), env=env, os_name=os_name, client_filter=client, single_file=target, key_env=args.key_env, deterministic=env.get("MCP_DOCTOR_DETERMINISTIC") == "1")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("\n".join(repair_lines) if repair_lines else "Nothing to repair.")
        return code
    if args.json:
        print(json.dumps(report, indent=2))
    elif args.report:
        print(markdown_report(report))
    else:
        print(text_report(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
