"""Live image insert for cleaned evidence narratives. Run from use-case folder."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["OPS_BUDGET_CAP"] = "200"

from generator.__main__ import _load_dotenv  # noqa: E402

_load_dotenv()

from generator.imagegen import generate_images_for_markdown  # noqa: E402
from generator.ledger import Ledger  # noqa: E402


async def main() -> int:
    key = os.environ.get("SUPERDOCS_API_KEY", "")
    if not key or key == "your-key-here":
        print("SUPERDOCS_API_KEY missing", file=sys.stderr)
        return 2
    ledger = Ledger()
    dest = ROOT / "evidence" / "narratives"
    verticals = ("legal", "fintech", "healthcare", "edtech")
    for code in verticals:
        path = dest / f"pitch-script-{code}-claritydocs.md"
        print(f"=== images {code} ===", flush=True)
        result = await generate_images_for_markdown(
            path,
            vertical=code,
            out_dir=dest,
            ledger=ledger,
        )
        rows = result.get("image_results") or []
        for row in rows:
            print(
                f"  s{row.get('section_number')} warranted={row.get('warranted')} "
                f"generated={row.get('generated')} skipped={row.get('skipped')} "
                f"ops={row.get('ops_charged')} status={row.get('ledger_status')}",
                flush=True,
            )
        print("  paths", result.get("paths"), flush=True)
    print("ledger_ops", ledger.total_operations, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
