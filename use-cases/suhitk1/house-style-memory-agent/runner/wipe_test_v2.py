"""Stage 6 (follow-up, not one of the original five): a stronger wipe test.

Stage 5's wipe test used a freshly-probed, narrow key and could not establish
a clean positive-control learning signal to demonstrate reversion against —
an honest null result, but it does not fully satisfy the brief's "proven by a
test" requirement on the wipe.

This follow-up reuses the ONE key already proven to hold real, measured
learning: `measurement_meridian_memory_on`, the key behind Stage 2's 9.4-point
effect (Stage 3 established the noise floor at 3.70, so that effect is
~2.5x noise, not noise itself). Protocol:

1. Wipe that key. Log the removed count — real content is expected this time,
   unlike Stage 5's fresh probe key.
2. Run ONE MORE document through the identical memory-on protocol
   (`run_one_document`, the same function Stage 1-3 used, imported rather
   than reimplemented) under that now-wiped key.
3. Compare the resulting score_before (the same metric the whole curve is
   built from) against three known reference points for the SAME document:
   memory_off (Stage 1), memory_off_repeat (Stage 3), and memory_on before the
   wipe (Stage 2). Reversion toward the memory-off pair is evidence the wipe
   genuinely wiped; a score still near the memory-on level would be evidence
   it did not.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import config
from checker.h3 import GeminiH3Provider
from checker.score import load_rubric
from corrections.generator import H3Cache, _CachedH3Provider, load_templates
from runner.experiment import CORPUS_DIR, MEMORY_ON_KEY, run_one_document
from superdocs.client import SuperDocsClient
from superdocs.mcp_transport import MCPHttpTransport

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--document", default="doc_18.md",
                    help="chosen for the cleanest Stage 2 signal: "
                         "off1=16, off2=19, on=2")
    ap.add_argument("--run-dir", type=str, default="runs/wipe_test_v2")
    args = ap.parse_args(argv)

    doc_path = CORPUS_DIR / args.document
    if not doc_path.exists():
        print(f"{doc_path} not found", file=sys.stderr)
        return 2

    run_dir = ROOT / args.run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    cache_path = run_dir / "h3_cache.json"
    if not cache_path.exists():
        cache_path.write_text("{}\n", encoding="utf-8")

    gemini_key = config.get("GEMINI_API_KEY")
    if not gemini_key:
        print("GEMINI_API_KEY is not set; H3 cannot be scored live.",
             file=sys.stderr)
        return 1
    cache = H3Cache(cache_path)
    h3_provider = _CachedH3Provider(GeminiH3Provider(gemini_key), cache)

    rubric = load_rubric("meridian")
    templates = load_templates()
    client = SuperDocsClient(MCPHttpTransport())

    print(f"Wiping {MEMORY_ON_KEY!r} — the Stage 2 measurement key, which "
         "holds real accumulated learning from 20 documents...")
    removed = client.clear_cross_session_memory(MEMORY_ON_KEY)
    print(f"  removed={removed}")

    print(f"\nRunning {args.document} through the identical memory-on "
         "protocol, post-wipe...")
    run = run_one_document(client, rubric, templates, h3_provider, doc_path,
                           "memory_on")
    before = run.score_before["totals"]["total_raw"]
    print(f"  score_before (the comparable metric) = {before}")

    out = {"wiped_key": MEMORY_ON_KEY, "removed": removed,
          "document": args.document, "post_wipe_score_before": before,
          "run": asdict(run), "ledger": client.ledger.as_dict()}
    out_path = run_dir / "results.json"
    out_path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"\nwritten: {out_path}")
    print(f"ops spent: {client.ledger.total_operations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
