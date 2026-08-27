# Committed sample output

Real output from the commands in the project README, committed so the build can
be inspected without running anything — and so a change that alters what the
pack produces shows up as a diff here.

Everything in this folder was produced **offline**, with no API key and no
billable operation. See the main README's *What has and has not been exercised*
section for exactly what that does and does not prove.

## The compliance index, in full

This is the document that makes *"correct and dated"* checkable, so it is
reproduced here as a table rather than only as an HTML file GitHub would render
as raw source. Every rule in the ruleset appears — **including the ones that did
not apply**, because a reviewer's question is usually "why is there no flood
disclosure here" and the honest answer is a row saying it was evaluated.

### Texas — `TX-AUS-4412` (runs clean, no flags)

| Ref | Requirement | Status | Authority | Verified | Review by |
| --- | --- | --- | --- | --- | --- |
| `—` | Lead-Based Paint Disclosure (Pre-1978 Housing) | Evaluated — does not apply | Residential Lead-Based Paint Hazard Reduction Act of 1992, 42 U.S.C. § 4852d | 2025-08-01 | 2027-06-30 |
| `—` | Delivery of EPA Lead Hazard Information Pamphlet | Evaluated — does not apply | 40 C.F.R. § 745.107(a)(1) | 2025-08-01 | 2027-06-30 |
| `D-1` | Flooding Disclosure | Included | Tex. Prop. Code § 92.0135 (H.B. 1523, 2019) | 2025-08-01 | 2027-03-31 |
| `D-2` | Vehicle Towing and Parking Rules Notice | Included | Tex. Prop. Code § 92.0131 | 2025-08-01 | 2027-03-31 |
| `L-1` | Smoke Alarms — Landlord Duty and Non-Waiver | Included | Tex. Prop. Code §§ 92.251–92.262 | 2025-08-01 | 2027-03-31 |
| `L-2` | Tenant's Repair Remedies — Required Notice of Procedure | Included | Tex. Prop. Code §§ 92.052, 92.056, 92.0561 | 2025-08-01 | 2027-03-31 |
| `L-3` | Security Deposit Refund — Thirty Days | Included | Tex. Prop. Code §§ 92.103, 92.104, 92.109 | 2025-08-01 | 2027-03-31 |
| `L-4` | No Statutory Security Deposit Cap (Jurisdiction Note) | Included | Tex. Prop. Code ch. 92, subch. C | 2025-08-01 | 2027-03-31 |
| `L-5` | Municipal Rent Control Preempted (Jurisdiction Note) | Included | Tex. Loc. Gov't Code § 214.902 | 2025-08-01 | 2027-03-31 |

The building is from 1985, so the two federal lead rules are recorded as
*evaluated and inapplicable* rather than omitted. `L-4` and `L-5` are the
jurisdiction notes that make an **absence** into a finding: Texas sets no deposit
cap and preempts municipal rent control, and both are cited.

### California — `CA-OAK-1187` (`--allow-stale`, two rules past review)

| Ref | Requirement | Status | Authority | Verified | Review by |
| --- | --- | --- | --- | --- | --- |
| `D-1` | Lead-Based Paint Disclosure (Pre-1978 Housing) | Included | Residential Lead-Based Paint Hazard Reduction Act of 1992, 42 U.S.C. § 4852d | 2025-08-01 | 2027-06-30 |
| `L-1` | Delivery of EPA Lead Hazard Information Pamphlet | Included | 40 C.F.R. § 745.107(a)(1) | 2025-08-01 | 2027-06-30 |
| `D-2` | Megan's Law Database Notice | Included | Cal. Civ. Code § 2079.10a | 2025-08-01 | 2027-03-31 |
| `D-3` | Bed Bug Information Notice | Included | Cal. Civ. Code § 1954.603 | 2025-08-01 | 2027-03-31 |
| `—` | Death on the Premises (Three-Year Lookback) | Evaluated — does not apply | Cal. Civ. Code § 1710.2 | 2025-08-01 | 2027-03-31 |
| `—` | Known Mold Disclosure | Evaluated — does not apply | Cal. Health & Safety Code § 26147 | 2025-08-01 | 2027-03-31 |
| `—` | Flood Hazard Disclosure | Evaluated — does not apply | Cal. Gov. Code § 8589.45 | 2025-08-01 | 2027-03-31 |
| `—` | Notice of Application for Demolition Permit | Evaluated — does not apply | Cal. Civ. Code § 1940.6 | 2025-08-01 | 2027-03-31 |
| `D-4` | Shared Utility Meter Disclosure | Included | Cal. Civ. Code § 1940.9 | 2025-08-01 | 2027-03-31 |
| `L-2` | Tenant Protection Act — Rent Cap and Just Cause Notice | **UNVERIFIED — past review date** | Cal. Civ. Code §§ 1946.2(f), 1947.12(d)(5) | 2025-08-01 | **2026-06-30** |
| `cap` | Security Deposit Cap — One Month's Rent | **UNVERIFIED — past review date** | Cal. Civ. Code § 1950.5(c), as amended by AB 12 (2023) | 2025-08-01 | **2026-06-30** |

Two things to look at here.

The last two rows carry review dates in the **past**, so this pack only exists
because it was generated with `--allow-stale`, and the override is stamped into
the document itself. Without that flag the run exits 2 and produces nothing.

The `cap` row is there because of a bug this build had and fixed. A deposit cap
is a *check*, not a document, so it gets no `D-`/`L-` reference — and the index
originally keyed its UNVERIFIED marking off document entries. A stale cap was
therefore invisible in the audit record, which is the most dangerous omission the
index could make: an out-of-date cap may approve a deposit that is no longer
lawful.

## The three documents of a pack

```bash
python -m real_estate_pack preview examples/tx_austin_apartment.yaml --out-dir docs/samples
```

| File | What to look at |
| --- | --- |
| [`TX-AUS-4412-lease.html`](TX-AUS-4412-lease.html) | The attachment schedule in section 4 names `D-1` and `D-2` — the same codes the packet uses. |
| [`TX-AUS-4412-disclosure_packet.html`](TX-AUS-4412-disclosure_packet.html) | The flooding notice carries a **Landlord's recorded answers** table: both answers are "No", and the notice is included anyway. A "no" is a disclosure, not an exemption. |
| [`TX-AUS-4412-compliance_index.html`](TX-AUS-4412-compliance_index.html) | The HTML source of the first table above. |
| [`CA-OAK-1187-*.html`](CA-OAK-1187-compliance_index.html) | The California pack, with `UNVERIFIED — past review date` on two rows and again in the list at the foot of the index. |

These are `.html`, so GitHub shows them as source in a diff — which is the point:
a change to what the pack produces is reviewable line by line. Open them locally
to see them styled.

## The card's premise, in one table

[`compare-four-jurisdictions.txt`](compare-four-jurisdictions.txt) — one property,
four rulesets:

```bash
python -m real_estate_pack compare examples/compare_all_jurisdictions.yaml
```

Nine disclosures are required in exactly one of the four jurisdictions, and the
same two-months deposit is lawful in Texas and Florida and unlawful in California
and New York.

## The blocking gate refusing to draft

[`blocked-unanswered-facts.txt`](blocked-unanswered-facts.txt) — what happens
when an applicability question has no answer:

```bash
python -m real_estate_pack check examples/incomplete_ca_unanswered.yaml
```

Exit code 2, five blocking findings, no API call, no operation spent. Note the
flood finding in particular: one of the two facts in that OR condition is
answered "no" and the other is missing, which is genuinely undecidable — so the
tool says so instead of guessing.
