# Renewal batch report

- Cycle: **2026-Q4** | run date 2026-08-20 | policy 2026.3
- Operations spent: **14** (500 remaining on the account)

## Processed accounts

| Account | Company | Price | Change | Gate | Status | Files |
| --- | --- | --- | --- | --- | --- | --- |
| ACM-1042 | Acme Industrial Supply Ltd | $42.00 -> $47.88 | +14.0% | increase of 14.0% exceeds the 8% gate; price-driven annual delta $21,944.16 exceeds $5,000.00 | exported (approved) | renewal-quote.docx<br/>price-change-notice.docx |
| NWL-2087 | Northwind Logistics plc | $30.00 -> $30.90 | +3.0% | auto | exported | renewal-quote.docx<br/>price-change-notice.docx |
| BPA-3310 | BluePeak Analytics GmbH | $45.00 -> $49.95 | +11.0% | increase of 11.0% exceeds the 8% gate; price-driven annual delta $5,702.40 exceeds $5,000.00 | exported (approved) | renewal-quote.docx<br/>price-change-notice.docx |
| FMF-7742 | Ferrous Manufacturing Co | $40.00 -> $36.00 | -10.0% | auto | exported | renewal-quote.docx<br/>price-change-notice.docx |
| GSC-8830 | Gulfstream Charter Partners | $32.00 -> $32.96 | +3.0% | account carries the churn_risk flag; any priced change is reviewed | rejected (rejected) | - |
| HLB-9114 | Helix Biosciences Ltd | $35.00 -> $40.25 | +15.0% | increase of 15.0% exceeds the 8% gate; price-driven annual delta $9,450.00 exceeds $5,000.00 | exported (approved) | renewal-quote.docx<br/>price-change-notice.docx |
| IWC-1201 | Ironwood Construction LLC | $30.00 -> $30.00 | +0.0% | auto | exported | renewal-quote.docx<br/>price-change-notice.docx |

## Deliberately not processed

| Account | Company | Why |
| --- | --- | --- |
| CHS-0771 | Cascade Health Systems Inc | open billing dispute; renewal paperwork is held until the dispute closes |
| DRM-5518 | Drift Media Collective | usage data is missing, so an account-specific notice cannot be honestly written; held for data backfill |
| EVR-6205 | Evergreen Retail Group | renewal date is outside the run window; the account belongs to a later batch |

## Rejected at the gate

| Account | Reviewer | Reason |
| --- | --- | --- |
| GSC-8830 | priya.ops@example.invalid | At-risk account: active seats fell from 17 to 9 and usage halved. No automated price-increase letter. Customer success calls first. |

## Batch completeness

**COMPLETE.** Every non-skipped account was exported or explicitly rejected; every skip has a named reason above.
