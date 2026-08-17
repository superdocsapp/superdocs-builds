"""Corpus prose stage. Requires GEMINI_API_KEY; makes one model call per draft.

Writes seed drafts verbatim to corpus/seed_drafts/ plus a provenance record.
Costs no SuperDocs operations. Small-sample default is n=3; the full n=20 needs
--n 20 explicitly, per the stopping rule in TASK.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

from gemini_client import MODEL, call_gemini

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / "corpus" / "prompts" / "seed_draft_v2.md"
PROMPT_VERSION = "seed_draft_v2"
TOPICS_PATH = ROOT / "corpus" / "topics.json"
OUT_DIR = ROOT / "corpus" / "seed_drafts"


def load_prompt_body() -> str:
    text = PROMPT_PATH.read_text("utf-8")
    start = text.index("## Prompt body (sent verbatim)")
    body = text[start:].split("\n", 1)[1]
    # Body ends at the next level-2 heading, whatever it is called.
    return re.split(r"^## ", body, maxsplit=1, flags=re.MULTILINE)[0].strip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3,
                    help="documents to generate (default 3, the dev sample)")
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be generated; makes no model call")
    ap.add_argument("--replace", type=int, default=None, metavar="NN",
                    help="regenerate document NN from a spare topic (used when "
                         "a draft is rejected for ignoring a structural "
                         "requirement; temperature 0 makes a retry pointless)")
    ap.add_argument("--spare", type=int, default=1, metavar="J",
                    help="1-based index into topics.json spares")
    args = ap.parse_args(argv)

    topics_doc = json.loads(TOPICS_PATH.read_text("utf-8"))
    topics = topics_doc["topics"]

    if args.replace is not None:
        spares = topics_doc.get("spares", [])
        if not 1 <= args.spare <= len(spares):
            print(f"--spare must be 1..{len(spares)}", file=sys.stderr)
            return 2
        args.start, args.n = args.replace, 1
        topics = list(topics)
        topics[args.replace - 1] = spares[args.spare - 1]
    if args.n > len(topics):
        print(f"only {len(topics)} topics defined", file=sys.stderr)
        return 2
    if args.n > 3 and not args.dry_run:
        print(f"NOTE: generating {args.n} drafts (dev sample is 3). "
              "Log this in PROGRESS.md.", file=sys.stderr)

    selected = topics[args.start - 1: args.start - 1 + args.n]
    if args.dry_run:
        for i, topic in enumerate(selected, start=args.start):
            print(f"doc_{i:02d}  {topic}")
        return 0

    import config
    api_key = config.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not set. The prose stage cannot run without "
              "it; no draft is written and nothing is faked.", file=sys.stderr)
        return 1

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    prompt_template = load_prompt_body()
    provenance = []
    for i, topic in enumerate(selected, start=args.start):
        prompt = (prompt_template
                  .replace("{{TOPIC}}", topic)
                  .replace("{{INDEX}}", str(i)))
        try:
            draft = call_gemini(prompt, api_key)
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            print(f"doc_{i:02d}: generation failed ({exc}); stopping. "
                  "Partial output is left in place and recorded.",
                  file=sys.stderr)
            break
        path = OUT_DIR / f"doc_{i:02d}.md"
        path.write_text(draft + "\n", encoding="utf-8")
        provenance.append({
            "document": path.name,
            "topic": topic,
            "model": MODEL,
            "prompt_version": PROMPT_VERSION,
            "temperature": 0,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(draft.encode()).hexdigest()[:16],
        })
        print(f"doc_{i:02d}: {len(draft.split())} words -> {path}")

    if provenance:
        prov_path = OUT_DIR / "provenance.json"
        existing = (json.loads(prov_path.read_text("utf-8"))
                    if prov_path.exists() else [])
        by_doc = {p["document"]: p for p in existing}
        by_doc.update({p["document"]: p for p in provenance})
        prov_path.write_text(
            json.dumps(sorted(by_doc.values(), key=lambda p: p["document"]),
                       indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
