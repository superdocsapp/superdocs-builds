*Fictional sample document created for software testing. No real person, company, agency, or case is depicted.*

# Answer key — case-2

**Case:** O-1A extraordinary ability (sciences), receipt SRC2590174382
**Beneficiary:** Dr. Anselm Ferreira-Duarte · **Petitioner:** Voltaris Grid Dynamics, Inc.
**Notice:** `notice/rfe-notice-src2590174382.md`, notice date 12 March 2026, eight numbered items.

**Petition documents on file:**

| File | Exhibit |
|---|---|
| `petition/petition-support-letter.md` | Counsel's support letter and exhibit index |
| `petition/exhibit-b1-expert-opinion-hargrove-sittig.md` | B-1 — independent academic expert letter |
| `petition/exhibit-b2-independent-adoption-letter-pallanton.md` | B-2 — independent operator adoption letter |
| `petition/exhibit-c-award-evidence-halvorsen-medal.md` | C — award evidence packet |
| `petition/exhibit-d-publication-and-citation-summary.md` | D — publications, citations, reviewer acknowledgement |
| `petition/exhibit-f-employment-agreement.md` | F — executed employment agreement |

---

## Coverage summary

| Item | Subject | Coverage |
|---|---|---|
| 1 | Consultation / peer group advisory opinion | **Not covered** |
| 2 | Certified English translations | **Not covered** |
| 3 | Nationally or internationally recognized awards — (B)(1) | **Fully covered** |
| 4 | Original contributions of major significance — (B)(5) | **Fully covered** |
| 5 | Authorship of scholarly articles — (B)(6) | **Fully covered** |
| 6 | Participation as a judge of the work of others — (B)(4) | **Partially covered** |
| 7 | High salary or remuneration — (B)(8) | **Partially covered** |
| 8 | Terms, dates and duties of the offered employment | **Fully covered** |

---

## Item-by-item

### Item 1 — Consultation (advisory opinion) from a peer group — NOT COVERED

No document in the petition set is or contains a peer-group or labor-organization advisory
opinion, the exhibit index at A–F lists none, and no petition document even mentions a
consultation; the two expert letters (B-1, B-2) were solicited by counsel to support the
evidentiary criteria and neither purports to be a peer-group opinion under 8 CFR 214.2(o)(5)(i).

### Item 2 — Certified English translations — NOT COVERED

Exhibit C-4 supplies only a photographic copy of the Portuguese engrossed citation plus a summary
written by counsel, and no translator certification of completeness, accuracy, or competence
appears in any petition document.

### Item 3 — Nationally or internationally recognized prizes or awards — FULLY COVERED

Exhibit C answers every sub-request: selection criteria grounded in excellence (C-2, Bylaws
Art. 9.3), external media beyond the Society's own membership (C-5, five outlets with
circulation), field and geographic pool with candidate numbers (C-2 Art. 9.2; C-3, 214 nominations
from 27 countries), the granting body's standing and the panelists' qualifications (C-1; C-3 panel
table), and prior recipients with their positions (C-6).

### Item 4 — Original scientific contributions of major significance — FULLY COVERED

Each sub-request has a matching source: independent deployment documented by the adopting entity
itself (B-2, Pallanton Municipal Power Authority, which expressly disclaims any relationship with
the petitioner), standards incorporation with the clause identified (B-1, NASSC 4412-2024
Clause 7.3.2 and Annex B), citation analysis with context (B-1's account of four extending groups
and a replication study; D Part 1 counts), and a detailed letter from an expert who explicitly
states he is not an employer, supervisor, co-author, or business partner (B-1).

### Item 5 — Authorship of scholarly articles — FULLY COVERED

Exhibit D Part 1 gives full titles, all authors in printed order, journal, volume, issue, pages
and dates; Part 3 gives each venue's editorial board, peer review model, acceptance rate,
readership, circulation figures and database indexing — matching all three sub-requests.

### Item 6 — Participation as a judge of the work of others — PARTIALLY COVERED

The *Journal of Grid-Scale Storage Systems* activity is fully documented (Exhibit D Part 4 gives
the appointment date, invitation-only selection process, fourteen reviews and each completion
date, corroborated by B-1), but the two other judging activities claimed in the support letter at
§5.4 — peer review for *Transactions on Electrochemical Systems Engineering* and the 2023
appointment to the Meridian Foundation grant review panel — have no invitation, confirmation,
count, or date anywhere in the petition set.

### Item 7 — High salary or other significantly high remuneration — PARTIALLY COVERED

Exhibit F documents what the beneficiary will be paid (§5.1 base USD 268,000, §5.2 signing bonus
USD 45,000, §5.3 target bonus, §5.4 a 14,000-unit RSU grant), but the criterion's comparative half
is absent: no wage survey, BLS or other published data, no statement of the occupational
classification or geographic area used for comparison, no evidence of past earnings actually
received, and no valuation of the equity.

### Item 8 — Terms, dates and duties of the offered employment — FULLY COVERED

Exhibit F §2.1 and §2.3 state the term as 1 June 2026 to 31 May 2029, matching the validity
requested on the I-129 exactly and expressly covering the whole period without interruption; §4.1
and §4.2 name both work locations, §4.3 addresses travel and confirms no third-party-controlled
worksite, and §9.3 states that no amendment, addendum, or side letter has been executed.

---

## Notes for test authors

- The two uncovered items are deliberately different in kind: Item 1 is a missing *statutory
  filing requirement* that no document alludes to, while Item 2 is a *defect in a document that is
  present* (Exhibit C-4 exists but is uncertified) — a system should surface both, and the second
  is the harder catch.
- Item 6's gap is a claim-versus-proof mismatch that is only visible by reading the support letter
  (§5.4, three activities claimed) against Exhibit D Part 4 (one activity documented). Neither
  document is deficient on its own.
- Item 7's gap is conceptual rather than missing-paperwork: the salary figure is present and
  prominent, so a system matching on keywords alone is likely to over-score this item as fully
  covered.
- Item 3 is designed as a "fully covered" item that a shallow reader may under-score, since the
  officer's five sub-requests are answered in five separate sub-sections of one exhibit.
