# Newsroom House-Style Pack & Style Drift Report

Built on SuperDocs for the Round 2 hiring task.

## Overview
A configuration-driven newsroom style checker and editing workflow built entirely on SuperDocs' upload → review → approve → export surface. A curated set of rules from **The Guardian Style Guide** is applied across a 20-article test set to measure recurring style drift, then used to review and apply corrections to three articles in place.

The rules live in a single data file (`house_style.json`), not in code — a rule change or a new rule is a config edit, not a rewrite.

## What I built
- `house_style.json` — 10 testable newsroom style rules, each with an ID, category, and precise wording, sourced from a real public style guide
- A 20-article audit run against the configured rules via SuperDocs
- A ranked, quantified style-drift report — violations counted and ranked by rule, not just listed
- Full SuperDocs review workflow (upload → audit → propose → review → approve → export) taken end-to-end on three articles
- Before/after corrections that preserve each article's original voice — targeted fixes, not rewrites
- A documented case where the checker was wrong, and why

## Style guide
**Source:** The Guardian Style Guide — https://www.theguardian.com/info/series/the-guardian-style-guide

Rules cover numbers, abbreviations, initials, quotation marks, jargon, usage, clarity, and word choice (full list and exact wording in `house_style.json`).

## Results

| Metric | Value |
|---|---|
| Articles audited | 20 |
| Planted violations | 78 |
| Violations reported by SuperDocs | 75 |
| Planted violations missed | 8 |
| Documented false positive | 1 |

**Most frequent drift, ranked:**
1. **G06** — "going forward" (jargon) — 20/20 articles
2. **G07** — "obligated" vs "obliged" (usage) — 20/20 articles
3. **G01** — number formatting —20 violations across 15 articles
4. **G04** — quotation marks — 15 violations across 15 articles

**Known limitation, stated plainly:** 78 planted − 8 missed = 70 violations that should exactly match a planted case. SuperDocs reported 75 total, and only 1 of the extra 5 findings was traced and documented as a clear false positive (see below). The remaining 4 were not individually re-traced against the planted set — a real gap in the audit's completeness, not a hidden one. A production version of this pipeline would assert a 1:1 match between every reported finding and a planted case, not just spot-check one.

## SuperDocs workflow
1. Upload newsroom article
2. Audit against `house_style.json` rules
3. Review flagged violations
4. Propose corrections
5. Review proposed diff before approval — voice-preserving, targeted edits only
6. Approve and export

Three articles were taken through this full loop, not just audited.

## Checker mistake
In Article 6, SuperDocs reported a G01 violation for **"8 store managers"** — a phrase that does not appear anywhere in the article. The article actually contains **"7 wards."** The finding was rejected, not applied. Kept in this report deliberately: a system that never shows its own mistakes is less trustworthy than one that catches and reports them.

## Files
- `house_style.json` — configurable newsroom style rules (edit this, not the pipeline, to add a rule)
- `newsroom-style-drift-report.docx` — full drift analysis, ranked report, and reviewed before/after examples

## Built for
SuperDocs Round 2 hiring task — Task 2, assigned build (Newsroom house-style pack and style-drift report).
