"""
run_sweep.py

One-command entry point for the freshness sweep. Runs, in order:
    find_affected -> propose_edits -> flag_screenshots -> score_freshness

By default it runs in SAMPLE mode against a fixed 3-article subset, so you
can eyeball the output shape and the matching logic before spending time on
the full 18-article corpus. Pass --full to run everything.

Spend cap
---------
This pipeline makes NO external LLM API calls -- find_affected.py's
change/article matches, propose_edits.py's edit text, and
flag_screenshots.py's visual-change judgments are all static logic authored
by Claude (Claude Code) against the actual article text. Runtime cost is
therefore local CPU time only.

    SPEND CAP FOR THIS SWEEP: $0.00 (no metered API calls in the pipeline)

If this pipeline is later wired up to a live LLM API for a larger or
non-synthetic corpus, set a real dollar cap before the first --full run and
have run_sweep enforce it the same way it currently enforces "sample must
run before full".

Usage:
    python run_sweep.py                 # sample mode (3 articles)
    python run_sweep.py --full          # full run (all articles), requires
                                         # at least one prior sample run
                                         # recorded in sweep_log.json
    python run_sweep.py --full --skip-verification-check
                                         # bypass the "sample ran first" gate
Writes/updates: affected_articles.json, proposed_edits.json,
flagged_screenshots.json, freshness_score.json, sweep_log.json
"""
import argparse
import datetime
import json
import time
from pathlib import Path

import find_affected as fa
import propose_edits as pe
import flag_screenshots as fs
import score_freshness as sf

BASE_DIR = Path(__file__).resolve().parent
ARTICLES_FILE = BASE_DIR / "articles.json"
CHANGES_FILE = BASE_DIR / "change_feed.json"
LOG_FILE = BASE_DIR / "sweep_log.json"

SPEND_CAP_USD = 0.00
DEFAULT_SAMPLE_IDS = ["art-001", "art-002", "art-003"]


def load_json(path, default=None):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_pipeline(mode, article_ids=None):
    all_articles = load_json(ARTICLES_FILE)
    changes = load_json(CHANGES_FILE)
    articles = (
        [a for a in all_articles if a["id"] in article_ids] if article_ids else all_articles
    )

    steps = []
    t_start = time.time()

    t0 = time.time()
    affected = fa.analyze(articles, changes)
    save_json(fa.OUTPUT_FILE, affected)
    steps.append({"step": "find_affected", "seconds": round(time.time() - t0, 4), "cost_usd": 0.0})

    t0 = time.time()
    edits = pe.analyze(articles, affected)
    save_json(pe.OUTPUT_FILE, edits)
    steps.append({"step": "propose_edits", "seconds": round(time.time() - t0, 4), "cost_usd": 0.0})

    t0 = time.time()
    flags = fs.analyze(articles, affected)
    save_json(fs.OUTPUT_FILE, flags)
    steps.append({"step": "flag_screenshots", "seconds": round(time.time() - t0, 4), "cost_usd": 0.0})

    t0 = time.time()
    score = sf.analyze(articles, affected)
    save_json(sf.OUTPUT_FILE, score)
    steps.append({"step": "score_freshness", "seconds": round(time.time() - t0, 4), "cost_usd": 0.0})

    total_seconds = round(time.time() - t_start, 4)

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": mode,
        "article_count": len(articles),
        "article_ids": sorted(a["id"] for a in articles),
        "change_count": len(changes),
        "steps": steps,
        "total_seconds": total_seconds,
        "total_cost_usd": 0.0,
        "spend_cap_usd": SPEND_CAP_USD,
        "portfolio_freshness_score": score["portfolio_freshness_score"],
        "affected_pairs": sum(len(r["affected_articles"]) for r in affected["results"]),
        "could_not_assess_pairs": sum(len(r["could_not_assess"]) for r in affected["results"]),
    }


def has_prior_sample_run():
    log = load_json(LOG_FILE, default=[])
    return any(entry.get("mode") == "sample" for entry in log)


def append_log(entry):
    log = load_json(LOG_FILE, default=[])
    log.append(entry)
    save_json(LOG_FILE, log)


def main():
    parser = argparse.ArgumentParser(description="Run the knowledge-base freshness sweep.")
    parser.add_argument(
        "--full", action="store_true", help="Run on the full article set instead of the 3-article sample."
    )
    parser.add_argument(
        "--sample-size", type=int, default=3, help="Number of articles to use in sample mode (default 3)."
    )
    parser.add_argument(
        "--skip-verification-check",
        action="store_true",
        help="Allow --full without a prior sample run already logged in sweep_log.json.",
    )
    args = parser.parse_args()

    print(f"Spend cap for this sweep: ${SPEND_CAP_USD:.2f} (no external LLM API calls -- local static matching only)")

    if args.full:
        if not has_prior_sample_run() and not args.skip_verification_check:
            print(
                "Refusing to run --full: no prior sample run found in sweep_log.json.\n"
                "Run `python run_sweep.py` (sample mode) first to verify the pipeline output, "
                "or pass --skip-verification-check to override."
            )
            raise SystemExit(1)
        print("Running FULL sweep...")
        result = run_pipeline(mode="full", article_ids=None)
    else:
        sample_ids = DEFAULT_SAMPLE_IDS[: args.sample_size]
        print(f"Running SAMPLE sweep on {sample_ids}...")
        result = run_pipeline(mode="sample", article_ids=sample_ids)
        print(
            "Sample run complete. Review affected_articles.json, proposed_edits.json, "
            "flagged_screenshots.json, and freshness_score.json, then re-run with --full."
        )

    append_log(result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
