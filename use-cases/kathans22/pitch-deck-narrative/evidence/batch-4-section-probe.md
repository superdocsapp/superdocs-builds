# Live probe — 4-section chat batch

**Date:** 18 August 2026 (IST)  
**Session:** `pitch-deck-narrative-batch-probe`  
**Test:** `tests/test_mcp_batch_live.py`

## Result

| Metric | Value |
|---|---|
| Landed | 1, 2, 3, 4 |
| Failed (unchanged) | (none) |
| Silent no-op? | **NO** — all four targeted sections changed |

## Compared to Build 1

Build 1 observed 4-section batches that returned success-shaped replies while the document was untouched ("went through 4 section(s) but nothing actually changed" / "Successfully updated all 4 sections" with no real edit).

**This probe did not reproduce that silent no-op.** On 18 Aug 2026, a single chat naming sections 1–4 produced real post-edit divergence from the `PLACEHOLDER_BODY_*` pre-edit text for every targeted section.

## What we do about it

- **Do not assume the silent no-op is gone forever** from one successful probe.
- **Keep `SUPERDOCS_CHAT_BATCH_CAP=2`** as the safe default (config, not folklore).
- **Keep landed-check + split-retry** — a success-shaped reply is still never trusted alone.
- If future probes repeatedly show 4-section batches landing reliably, raising the cap can be a logged, measured decision — not a silent change.

## Post-edit fingerprints (normalised, truncated)

- section 1: includes distinct rewritten prose (placeholder gone)
- section 2: includes distinct rewritten prose (placeholder gone)
- section 3: includes distinct rewritten prose (placeholder gone)
- section 4: includes `landed_section_4` marker / distinct prose (placeholder gone)
