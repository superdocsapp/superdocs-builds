#!/usr/bin/env python3
"""
Merges the `superdocs` MCP server entry into the real global config file for
Windsurf or Cline -- a MERGE, not an overwrite, because both files are
global (shared across every workspace the host has open) and almost
certainly already have other MCP servers configured in them that this must
not clobber.

Real paths, verified against current docs while building this (both
products' config layouts changed since this repo's task brief was written --
Windsurf's docs now live under docs.devin.ai after a rebrand; `.windsurf/rules/`
still works as the documented legacy fallback path):

  Windsurf: ~/.codeium/windsurf/mcp_config.json           (all platforms)
  Cline:    %APPDATA%/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json   (Windows)
            ~/Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json  (macOS)
            ~/.config/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json   (Linux)

Usage:
  python install.py windsurf
  python install.py cline
  python install.py windsurf --dry-run   # print what would change, touch nothing
"""

import argparse
import json
import platform
import sys
from pathlib import Path

SUPERDOCS_ENTRY_WINDSURF = {
    "serverUrl": "https://api.superdocs.app/mcp",
    "headers": {"Authorization": "Bearer ${env:SUPERDOCS_API_KEY}"},
}

SUPERDOCS_ENTRY_CLINE = {
    "type": "streamableHttp",
    "url": "https://api.superdocs.app/mcp",
    "headers": {"Authorization": "Bearer ${env:SUPERDOCS_API_KEY}"},
    "disabled": False,
    "autoApprove": [],
}


def windsurf_config_path() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


def cline_config_path() -> Path:
    system = platform.system()
    if system == "Windows":
        import os

        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
    return Path.home() / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"


def merge(config_path: Path, entry: dict, dry_run: bool) -> None:
    if config_path.exists():
        existing = json.loads(config_path.read_text() or "{}")
    else:
        existing = {}

    existing.setdefault("mcpServers", {})
    already_present = existing["mcpServers"].get("superdocs") == entry
    existing["mcpServers"]["superdocs"] = entry

    print(f"Target file: {config_path}")
    print(f"Existing other servers preserved: {[k for k in existing['mcpServers'] if k != 'superdocs']}")
    print("New/updated entry:")
    print(json.dumps({"superdocs": entry}, indent=2))

    if already_present:
        print("Already up to date -- no write needed.")
        return

    if dry_run:
        print("(dry run -- not writing)")
        return

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        backup.write_text(config_path.read_text())
        print(f"Backed up existing config to {backup}")
    config_path.write_text(json.dumps(existing, indent=2) + "\n")
    print("Written.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host", choices=["windsurf", "cline"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.host == "windsurf":
        merge(windsurf_config_path(), SUPERDOCS_ENTRY_WINDSURF, args.dry_run)
    else:
        merge(cline_config_path(), SUPERDOCS_ENTRY_CLINE, args.dry_run)

    print("\nDon't forget: export SUPERDOCS_API_KEY=sk_... in the environment the host launches from "
          "(both configs reference it via ${env:SUPERDOCS_API_KEY}, never a hardcoded key).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
