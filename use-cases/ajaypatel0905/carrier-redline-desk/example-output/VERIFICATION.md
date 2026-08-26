# Verification Report

Run: `example-run` · session `redline-example-run-1d6712c1ddd1` · 2026-08-26T17:26:31Z

## Untouched means byte-identical
- Chunks not governed by an approved change: **24**; byte-identical to the uploaded parse: **24** ✅

## Redline round-trip proofs
- 14 proofs (reject-all == original, accept-all == approved text, byte-identical): **all pass** ✅

## Summary and redline cannot disagree
- Both are generated from the same change records; there is no second source of truth.
- Records: 13 · approved: 12 · acceptable-untouched: 1 · denied: 0

## Embedded instructions in the source
- 1 flagged; reported in the negotiation summary, none obeyed.

## Cost
- Operations charged, by stage: {"rules:R-101": 1, "rules:R-102": 1, "rules:R-103": 1, "rules:R-104": 1, "rules:R-105": 1, "rules:R-106": 1, "rules:R-107": 1, "rules:R-108": 1, "rules:R-110": 1, "rules:R-111": 0, "rules:R-112": 1} (uploads and exports are unbilled)
