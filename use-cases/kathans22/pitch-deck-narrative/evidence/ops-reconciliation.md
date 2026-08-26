# Ops reconciliation — actual ledger vs CLAUDE.md estimate

**Source ledger:** `evidence/ledger-four-verticals.json`  
**Printed report:** `evidence/ledger-four-verticals-report.txt`  
**Date:** 2026-08-18

## Headline

| | Ops |
|---|---|
| **CLAUDE.md estimate (4 verticals)** | **~20** |
| **Actual charged total** | **39** |
| Delta | **+19 (~2×)** |

Still well inside the 10,000-operation budget.

## CLAUDE.md economics (what “~20” assumed)

From `CLAUDE.md`:

- 9 sections ÷ 2 per batch → **5 batched chat calls per vertical**
- **1 op per chat call** when a change applies (worst case, **no landed-check retries**)
- Export / download / divergence / guard / score → **0 ops**
- Four verticals → **5 × 4 = ~20 ops**

That estimate is a **happy-path floor**: one successful billable chat per planned batch, then stop.

## Actual charged chat ops by vertical

Each vertical still ran **5 planned batches** (sections `[1,2] [3,4] [5,6] [7,8] [9]`). Charged ops per batch often exceeded 1 because of landed-check **split-retry** (and any billable follow-up calls the API recorded in `usage`).

| Vertical | Planned batches | Charged chat ops | vs estimate (5) |
|---|---|---|---|
| legal | 5 | **10** | +5 |
| fintech | 5 | **12** | +7 |
| healthcare | 5 | **9** | +4 |
| edtech | 5 | **8** | +3 |
| **Total** | **20** | **39** | **+19** |

Per-batch charges (from the ledger):

- legal: 2 + 2 + 1 + 3 + 2 = 10  
- fintech: 3 + 3 + 2 + 3 + 1 = 12  
- healthcare: 1 + 3 + 1 + 3 + 1 = 9  
- edtech: 3 + 1 + 1 + 1 + 2 = 8  

Upload, export, generate-marker, guard, score, and the legal **SKIPPED** re-run all charged **0** — matching CLAUDE on non-chat steps.

## Why the estimate is meaningfully low (before you look)

1. **Landed-check split-retry is the main driver.** CLAUDE’s “5 ops / vertical” explicitly assumes *no* retries. When a 2-section batch fails the landed-check for one section, the client retries that section alone — each retry is another billable chat when `usage.was_billable` is true. Batches that show **2** or **3** ops are planned call + retry(s), not “we ran six section groups.”
2. **The estimate counts planned batches, not API usage records.** Live SuperDocs can return multiple billable interactions for one logical batch (approve/apply path, compact retries). The ledger records what `ops_from_response` / fallback charging saw — not “1 per `chunk_section_numbers` row.”
3. **Idempotent re-runs did not inflate the total.** Legal’s second `generate` is `SKIPPED (0 ops)`. The +19 is all from first-pass chat charges, not from regenerating verticals.

## Revised rule of thumb (for later budgeting)

Treat **~8–12 ops per vertical** as the observed band with landed-check retries on, or **~2×** the CLAUDE happy-path number. Four verticals ≈ **35–45 ops** in this run (**39** actual). Images (Phase later) are still separate and must be confirmed against live docs before adding to this total.

## Still true from CLAUDE.md

- Export, download, divergence scoring: **0 ops** ✓  
- Guard / score / ledger markers: **0 ops** ✓  
- Optional fourth vertical is affordable ✓  
- Far under the 10,000-op budget ✓
