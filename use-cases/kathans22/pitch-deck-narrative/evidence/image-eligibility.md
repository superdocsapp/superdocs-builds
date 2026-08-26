# Image eligibility decisions — four verticals

**Date:** 18 August 2026 (updated after live insert)  
**Eligible sections (manifest):** 6 Proof / Case Study, 8 ROI / Business Case.

Sidecars (`pitch-script-<vertical>-claritydocs.meta.json`) are written **before** image chat. Machine-readable copy: `evidence/image-eligibility.json`.

## Eligibility table (after substance rework)

| Vertical | §6 Proof | §8 ROI |
|---|---|---|
| legal | **yes** (Northbridge 12 / 2 / 10) | **yes** (hours vs weeks) |
| fintech | **yes** (HarborPay 12 / 4 / 8) | **yes** (hours vs weeks) |
| healthcare | **yes** (Cedar Ward 3 / 1 / 2) | **yes** (weeks vs one pass) |
| edtech | **yes** (Lumen State 4 / 1 / 3) | **yes** (weeks vs same-day export) |

**Warranted:** 8 of 8 eligible cells. **Live insert:** 8 chat ops. Local mirrors: `evidence/narratives/presenter-visuals/`.

## Billing

Image generation is a normal document-edit **chat** operation (typically 1 op). Not a separate SKU. `IMAGE_GENERATION_BILLING_CERTAIN = True`.

## Live generation

**Executed 18 August 2026** with a local `.env` key (not committed). Healthcare chat also appended extra generic sections — see BUG-002; those blocks were stripped from the evidence markdown.
