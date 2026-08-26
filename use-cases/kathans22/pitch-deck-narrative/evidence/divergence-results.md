# Divergence results — four verticals (Prompt 14)

**Date:** 2026-08-18  
**Verticals:** legal, fintech, healthcare, edtech  
**Source:** `evidence/narratives/pitch-script-*-claritydocs.md`  
**Machine report:** `evidence/divergence-report.json`  
**Metric:** word Jaccard · Phase 1 thresholds `VERTICAL_MEAN_MAX=0.40`, `VERTICAL_SECTION_MAX=0.55`

## Verdict: **PASS**

| Aggregate | Value | Gate |
|---|---|---|
| Mean overlap — **vertical-tagged** sections | **0.115** | must be **&lt; 0.40** |
| Mean overlap — **shared-tagged** sections | **0.186** | reported only (not gated) |
| Vertical cells scored | 36 | 6 pairs × 6 vertical sections |
| Shared cells scored | 18 | 6 pairs × 3 shared sections |
| Hot sections (≥ 0.55) | **none** | any one fails the run |

Shared mean is higher than vertical mean (expected direction: product framing overlaps more than vertical substance). No vertical-tagged cell reached the template-and-swap ceiling — the highest vertical cell is **0.207** (edtech↔legal section 2; fintech↔healthcare section 7).

## Highest vertical-tagged cells (not averaged away)

| Section | Pair | Score | ≥ 0.55? |
|---|---|---|---|
| 2 Problem | edtech ↔ legal | 0.207 | no |
| 7 Objection | fintech ↔ healthcare | 0.207 | no |
| 7 Objection | fintech ↔ legal | 0.197 | no |
| 7 Objection | healthcare ↔ legal | 0.185 | no |
| 3 Why Now | fintech ↔ healthcare | 0.180 | no |
| 2 Problem | fintech ↔ legal | 0.171 | no |

No template-and-swap failure: nothing at or above `VERTICAL_SECTION_MAX`.

## Per-pair means

| Pair | Mean vertical | Mean shared |
|---|---|---|
| edtech ↔ fintech | 0.101 | 0.121 |
| edtech ↔ healthcare | 0.107 | 0.119 |
| edtech ↔ legal | 0.102 | 0.149 |
| fintech ↔ healthcare | 0.151 | 0.136 |
| fintech ↔ legal | 0.115 | 0.135 |
| healthcare ↔ legal | 0.116 | 0.459 |

Healthcare↔legal shared mean is elevated mainly by section 4 (Product Overview) at **1.000** — identical product overview copy, allowed for `shared`-tagged sections and not a gate failure.

Full per-pair-per-section matrix is in `divergence-report.json` → `report.pairs[].sections`.

## Rework needed (coverage — not a high-overlap fail)

**edtech · section 7 (Objection Handling)** — missing from the scorer.

The export used a nonstandard heading:

`## Navigating Institutional Resistance: Strategic Objection Handling in EdTech Implementation`

instead of:

`## Slide-equivalent 7 — Objection Handling`

So `parse_script_sections` did not bind section 7 for edtech. Those pair cells score **0.0** (empty vs filled), which **lowers** the vertical mean rather than inflating it. Still a quality defect: rework the edtech heading (or regenerate that section) before treating Objection as fully scored for edtech pairs.

Also noted from earlier runs (BUG-001 class): leftover `PLACEHOLDER_*` lines under some filled sections across verticals — does not flip this divergence PASS, but should be cleaned in a later quality pass.

## How to re-run (0 SuperDocs ops)

```bash
python -m generator score --from evidence/narratives
```
