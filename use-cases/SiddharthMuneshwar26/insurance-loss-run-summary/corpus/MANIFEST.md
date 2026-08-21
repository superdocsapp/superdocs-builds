# MANIFEST — ground truth for the synthetic loss-run corpus

Everything in this corpus is fabricated. Meridian Cold Chain Logistics, Kestrel
Mutual Insurance and Ardent Risk Partners do not exist. No figure is drawn from
any real claim, policy or company.

This file is the answer key. A system reading this corpus should surface the
conflicts and findings below, and should surface **nothing that is not on this
list**. Both halves matter: a corpus with a known-clean remainder is what makes
a false positive visible.

Regenerate with `python generate.py`. The seed is fixed, so the corpus is
byte-stable.

## Contents

| file | format | role |
|---|---|---|
| `loss-runs/loss-run-2021-valued-2024-01.csv` | CSV | policy year 2021, 12 claims |
| `loss-runs/loss-run-2022-valued-2024-01.csv` | CSV | policy year 2022, 12 claims |
| `loss-runs/loss-run-2022-valued-2024-01.pdf` | PDF | same content, different format |
| `loss-runs/loss-run-2023-valued-2024-01-ORIGINAL.csv` | CSV | **superseded** 2023 run, 9 claims |
| `loss-runs/loss-run-2023-valued-2026-01-REISSUE.csv` | CSV | **authoritative** 2023 run, 10 claims |
| `loss-runs/loss-run-2024-valued-2026-01.csv` | CSV | policy year 2024, 7 claims |
| `adjuster-notes/*.docx` | DOCX | three claim file notes |
| `application/meridian-renewal-application-2026.docx` | DOCX | signed renewal application |
| `correspondence/ardent-cover-note-2026-01-28.docx` | DOCX | broker cover note |
| `rules/underwriting-checklist.docx` | DOCX | the eight rules to examine against |

41 claims across four policy years.

## The conflict that changes the decision

Claim **KM-2023-0417** (jackknife on I-80) carries **$45,000.00** incurred on the
2023 run valued January 2024, and **$182,400.00** on the reissue valued January
2026. Neither document is wrong — the reserve developed after suit was filed,
and the adjuster note sets out the history.

The consequence is not cosmetic:

| source for policy year 2023 | incurred | earned premium | loss ratio | rule R3 |
|---|---|---|---|---|
| original run, valued 2024-01 | $286,092.44 | $501,200 | **57.1%** | passes |
| reissue, valued 2026-01 | $647,992.44 | $501,200 | **129.3%** | **refer** |

The same account either clears the referral threshold or blows through it twice
over, depending on which document is trusted. A system that silently picks one
has made an underwriting decision without telling anyone. This is the conflict
to surface rather than resolve.

## Planted conflicts

**C1 — reserve development across a reissue.** KM-2023-0417, $45,000.00 →
$182,400.00. Adjuster note dated 2025-09-30 explains it and gives the reserve
history. Consequence above.

**C2 — status contradicted by a later note.** KM-2022-0311 is `Closed` on every
loss run. The adjuster note dated 2024-03-12 states the claim reopened on
2024-02-19 with a re-established reserve of $34,000. The note explicitly says the
loss run was correct at its valuation date and is no longer correct. The loss
runs were never reissued to reflect it.

**C3 — claim present in the reissue and absent from the original.**
KM-2023-0588, $224,500.00, date of loss 2024-02-27, reported 2024-06-14 — after
the original run was issued. Only document where it appears first: the reissue.

**C4 — date of loss outside its stated policy period.** KM-2022-0402 has a date
of loss of 2023-04-11 but is filed under policy year 2022, which ran to
2023-04-01. Triggers R4.

**C5 — one event under two claim numbers.** KM-2021-0219 and KM-2021-0224 both
describe a bridge strike on Route 6 on 2021-08-03, each at $27,450.00. The 2021
total therefore double-counts $27,450.00. Triggers R7.

**C6 — severity claim with no adjuster note.** KM-2024-0106, $149,000.00
incurred, open. No note in the corpus. Triggers R1.

**C7 — dormant reserve.** KM-2021-0333, $0.00 paid against a $96,000.00 reserve,
open 49 months at the January 2026 valuation. Triggers R2 and R6.

**C8 — loss run that does not add up.** The original 2023 run states a total
incurred of $287,592.44; its rows sum to $286,092.44. A $1,500.00 discrepancy.
Real loss runs do this. Triggers R8. The other four runs are internally
consistent — check them and find nothing.

**C9 — application contradicts the loss runs, three ways.** The signed
application dated 2026-01-22 states:

| application says | loss runs show |
|---|---|
| 3 claims exceeding $50,000 in five years | **7** |
| no open claim exceeds $100,000 | **3** (KM-2023-0417, KM-2023-0588, KM-2024-0106) |
| all 2021 and 2022 claims are closed | **6 still open** |

The broker's cover note explains why — the application was prepared in December,
before the reissued runs arrived. That explanation is in a different document
from the contradiction, which is the point.

## Findings the checklist should produce

Against the **authoritative** set (2021, 2022, 2023-reissue, 2024):

| rule | expected findings |
|---|---|
| R1 adjuster note on ≥$100k | 1 — KM-2024-0106 |
| R2 open >36 months | 4 — KM-2021-0232, KM-2021-0252, KM-2021-0333, KM-2022-0237 |
| R3 loss ratio >60% | 1 — policy year 2023 at 129.3% |
| R4 policy period integrity | 1 — KM-2022-0402 |
| R5 application consistency | 3 — the rows in C9 |
| R6 dormant reserve >24 months | 1 — KM-2021-0333 |
| R7 duplicate claims | 1 — KM-2021-0219 / KM-2021-0224 |
| R8 loss run adds up | 1 — original 2023 run, $1,500.00 out |

Loss ratios by year, for R3: 2021 **57.6%**, 2022 **41.2%**, 2023 **129.3%**,
2024 **33.3%**. Three of four pass, which is what makes the fourth mean
something.

## Deliberately clean

The other 34 claims carry no planted defect. Every one of the four policy years
except 2023 is internally consistent, under the loss-ratio threshold, and free
of period or duplicate problems. Anything a system reports outside the table
above is a false positive, and on this corpus that is measurable rather than a
matter of opinion.

## A note on formats

The 2022 loss run exists as both CSV and PDF with identical content. A system
that claims to handle mixed formats can be checked on it: the same policy year,
read two ways, must produce the same facts.
