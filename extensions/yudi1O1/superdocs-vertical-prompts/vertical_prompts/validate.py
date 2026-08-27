"""python -m vertical_prompts.validate packs/legal/pack.yaml

Loads and structurally validates a pack.yaml without starting an MCP server —
catches the same errors `load_pack` would raise, with a process exit code
CI can check."""
from __future__ import annotations

import argparse
import sys

from .pack_spec import PackSpecError, load_pack


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vertical_prompts.validate")
    parser.add_argument("pack_path")
    args = parser.parse_args(argv)

    try:
        pack = load_pack(args.pack_path)
    except PackSpecError as e:
        print(f"INVALID: {e}")
        return 1

    print(f"OK: '{pack.display_name}' ({pack.pack_id}) — {len(pack.commands)} command(s):")
    for c in pack.commands:
        args_desc = ", ".join(f"{a.name}{'' if a.required else '?'}" for a in c.arguments) or "(no arguments)"
        print(f"  /{pack.pack_id}:{c.id}  [{c.approval_mode}, export={c.export.format}]  args: {args_desc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
