#!/usr/bin/env python
"""Regenerate docs/transcripts/ by actually calling the running MCP server.

The transcripts in docs/ are captured output, not hand-written examples — this
script is what captures them, so anyone can verify the documented prompts match
what the server really returns:

    python scripts/capture_transcripts.py
    git diff --exit-code docs/transcripts/    # clean == docs match reality

No SuperDocs API key needed: prompts render text locally, they never call the
SuperDocs API themselves.
"""
from __future__ import annotations

import asyncio
import os
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from mcp.client.session import ClientSession  # noqa: E402
from mcp.client.stdio import StdioServerParameters, stdio_client  # noqa: E402

#: One representative, realistic invocation per command. Synthetic parties only.
CASES: list[tuple[str, str, dict[str, str]]] = [
    ("packs/legal/pack.yaml", "redline", {
        "contract_description": "the vendor MSA currently open in this session",
        "focus_areas": "limitation of liability and indemnification",
        "negotiating_position": "our standard playbook favors mutual indemnification capped at 12 months' fees",
    }),
    ("packs/legal/pack.yaml", "fallback_clause", {
        "clause_name": "the limitation of liability clause (Section 9.1)",
        "primary_position": "cap liability at 12 months' fees, mutual",
        "fallback_position": "raise the cap to 24 months' fees but keep the mutual carve-out for gross negligence",
    }),
    ("packs/legal/pack.yaml", "draft_from_playbook", {
        "document_type": "a mutual NDA",
        "counterparty": "Northwind Logistics GmbH",
        "key_terms": "2-year term, mutual confidentiality, Delaware law, 30-day termination for convenience",
    }),
    ("packs/legal/pack.yaml", "obligation_summary", {
        "contract_description": "the vendor MSA currently open in this session",
    }),
    ("packs/real_estate/pack.yaml", "draft_disclosure", {
        "property_description": "123 Maple St., built 1974, known history of a basement water issue repaired in 2019",
        "disclosure_type": "material defect disclosure (water intrusion)",
        "jurisdiction": "California",
    }),
    ("packs/real_estate/pack.yaml", "compare_addendum", {
        "addendum_description": "the financing contingency extension addendum the buyer's agent sent yesterday",
        "base_agreement_description": "the original purchase agreement open in this session",
    }),
    ("packs/real_estate/pack.yaml", "closing_checklist", {
        "transaction_description": (
            "the purchase agreement, inspection addendum, and financing contingency for the "
            "123 Maple St. purchase, all open in this session"
        ),
        "closing_date": "2026-10-15",
    }),
]


async def capture(pack_path: str, command_id: str, args: dict[str, str]) -> str:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "vertical_prompts.server", "--pack", pack_path],
        cwd=ROOT,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.get_prompt(command_id, args)
            return result.messages[0].content.text


async def main() -> int:
    out_dir = os.path.join(ROOT, "docs", "transcripts")
    os.makedirs(out_dir, exist_ok=True)
    for pack_path, command_id, args in CASES:
        pack_name = os.path.basename(os.path.dirname(pack_path))
        text = await capture(pack_path, command_id, args)
        args_block = "\n".join(f"  {k}: {v!r}" for k, v in args.items())
        content = (
            f"# `/{pack_name}:{command_id}`\n\n"
            f'Real output from `session.get_prompt("{command_id}", ...)` against the actual running server\n'
            f"(`python -m vertical_prompts.server --pack {pack_path}`) — captured, not hand-written.\n"
            f"Regenerate with `python scripts/capture_transcripts.py`.\n\n"
            "**Slash-command invocation** (as a user would type it in Claude Code / Claude Desktop / Cursor):\n\n"
            f"```\n/{pack_name}:{command_id}\n{args_block}\n```\n\n"
            "**Rendered prompt message the assistant receives:**\n\n"
            f"```\n{text}\n```\n"
        )
        path = os.path.join(out_dir, f"{pack_name}-{command_id}.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"wrote docs/transcripts/{pack_name}-{command_id}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
