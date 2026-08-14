# Freshness Sweeper

A knowledge-base freshness sweeper built against a synthetic help center for a fictional SaaS product ("Cascade"). It answers one question: **when a product changes, which help articles are now wrong, and where exactly?**

## What it does

Help centers rot quietly. A rate limit gets bumped, a button gets renamed, a plan's storage allowance changes -- and the docs that mention the old value just sit there, technically published, quietly wrong. Worse, plenty of staleness never uses the old number or term at all: an article might just say "you'll have plenty of time" instead of "24 hours," and a plain keyword search over the docs would never catch it.

This project simulates that problem end to end with fully synthetic data:

- **`articles.json`** -- 18 fictional help-center articles covering password reset, API rate limits, billing/plans, webhooks, exporting data, team permissions, and more. Several of them describe soon-to-be-outdated behavior *without* stating the specific number or term that's about to change, on purpose -- so a naive keyword-matcher can't find them.
- **`change_feed.json`** -- 6 fictional product changes (e.g. API rate limit 100 -> 500 req/min, "Export" renamed to "Download", Starter plan storage 5GB -> 20GB, legacy webhook v1 retired).
- A four-stage pipeline that, for each change, finds every affected article (direct *and* indirect/implied mentions), proposes a surgical one-sentence edit per affected article, flags which screenshots visually depict the changed element, and rolls everything up into a portfolio freshness score plus a "could not assess" list for genuinely ambiguous cases that need a human.

The whole thing runs as one command, with a small-sample verification mode before you commit to the full run, and a timing/cost log so a run's cost is never a surprise.

## How to run it

Requires Python 3.9+ (standard library only -- no dependencies to install).

```bash
cd extensions/WesleyStevePaul/freshness-sweeper

# 1. Sample mode (default): runs the full pipeline on a fixed 3-article
#    subset so you can sanity-check the output shape cheaply first.
python run_sweep.py

# 2. Review the output files it just wrote:
#    affected_articles.json, proposed_edits.json,
#    flagged_screenshots.json, freshness_score.json

# 3. Once you're happy, run the full 18-article sweep:
python run_sweep.py --full
```

`--full` refuses to run until at least one sample run has been logged to `sweep_log.json` (pass `--skip-verification-check` to bypass that gate deliberately). Every run appends a timing entry to `sweep_log.json`; the pipeline makes no external/paid API calls, so the logged cost is always `$0.00` (see "SuperDocs features used" below for why).

You can also run any stage on its own once `affected_articles.json` exists:

```bash
python find_affected.py       # change_feed.json + articles.json -> affected_articles.json
python propose_edits.py       # -> proposed_edits.json
python flag_screenshots.py    # -> flagged_screenshots.json
python score_freshness.py     # -> freshness_score.json
```

## What SuperDocs features this uses

Honestly: **none directly.** This is a standalone Python script with no SuperDocs API calls, no MCP server, and no backend of any kind -- it reads two local JSON files and writes local JSON files. That's a deliberate choice, not an oversight: the task card explicitly allows this build to be "completed without building a backend," and a self-contained script was the most direct way to demonstrate the actual matching/scoring logic without extra infrastructure obscuring it.

The semantic matching (including the indirect/implied mentions, which is the hard part of this problem) was done by Claude Code during authoring and is encoded as inspectable, evidence-backed logic in `find_affected.py`, `propose_edits.py`, and `flag_screenshots.py` -- not via a live LLM API call at run time. That's why every pipeline run costs `$0.00` and completes in milliseconds.

## Demo video

A walkthrough demo video will be linked separately as part of the hiring round submission.
