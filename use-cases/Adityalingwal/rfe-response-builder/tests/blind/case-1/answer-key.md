# Answer key — case-1

> FICTIONAL SAMPLE. This document was created for software testing. All names, companies, schools, addresses, receipt numbers, and dates are invented.

Case: H-1B petition WAC-26-118-50432, Calderon Ridge Robotics, Inc. on behalf of Nikhil Arjun Baranwal, Controls Systems Engineer II. Requested validity October 1, 2026 – September 30, 2029.

Notice: `notice/i-797e-request-for-evidence.md` — six numbered requests.

## Coverage at a glance

| Item | Subject | Coverage |
|---|---|---|
| 1 | Specialty occupation | **Fully covered** |
| 2 | Beneficiary's qualifications | **Fully covered** |
| 3 | Employer-employee relationship and control at the third-party worksite | **Partially covered** |
| 4 | LCA correspondence to the petition | **Partially covered** |
| 5 | Maintenance of status and eligibility for change of status | **Not covered** |
| 6 | Petitioner as a United States employer doing business | **Fully covered** |

## Item-by-item

### Item 1 — The proffered position as a specialty occupation → FULLY COVERED

Every sub-request has matching evidence in the petition: duties with percentage allocations and the specialized knowledge each requires (`02-employer-support-letter.md`, section 2 and 3); parallel-position announcements from five comparable integrators plus an industry survey figure (`03-position-description-and-hiring-standard.md`, Part 4); the petitioner's written mandatory degree standard and the degrees held by all six prior and current incumbents (same file, Parts 1 and 3); and the complexity comparison against Engineer I and Technician III levels, backed by the organizational chart at `06-corporate-and-organizational-documents.md`, F-5.

### Item 2 — The beneficiary's qualifications → FULLY COVERED

`04-beneficiary-credentials-packet.md` supplies each sub-request: both diplomas (D-1, D-3), complete transcripts with courses, grades, and conferral dates (D-2, D-4), a credential evaluation stating U.S. bachelor's equivalency with its stated basis and the evaluator's competence (D-6), and evidence that both institutions are accredited or officially recognised (D-2 note and D-5). The specialties named — Robotics Engineering and Mechatronics Engineering — are on the position's required list.

### Item 3 — Employer-employee relationship and right to control → PARTIALLY COVERED

Some of what the officer asked for is present and some is absent. Present: contractual control language reserving hiring, supervision, review, and substitution to the petitioner (`05-client-services-agreement-and-work-order.md`, Article 4), the named supervising employee and the semi-annual review practice (`02-employer-support-letter.md`, section 5), and a signed work order. Absent: any letter from Talleyburn Foods Group on its own letterhead (sub-request a); contracts covering the **entire** validity period — the master agreement ends December 31, 2027 and the work order ends June 30, 2027, leaving roughly the last 27 months of the requested period undocumented (sub-request b); and any itinerary of definite employment (sub-request c).

### Item 4 — LCA correspondence to the petition → PARTIALLY COVERED

The cover letter states the certified LCA's case number, SOC code 17-2199, Level II wage, prevailing wage, offered wage, and certification period, which answers the classification, wage-level, and wage parts of the request. But the LCA of record lists only the Ashfield, Ohio worksite, while the work order places on-site commissioning at Fort Grelling, Indiana — a different area of intended employment. No second LCA is in the petition, and no written explanation invoking the short-term placement or non-worksite provisions appears anywhere.

### Item 5 — Maintenance of status and eligibility for change of status → NOT COVERED

Nothing in any of the six petition documents addresses the beneficiary's immigration status. There is no Form I-94, no Form I-20, no employment authorization document, no passport or visa copy, and no statement accounting for periods of non-employment. The cover letter's enclosure list contains no status documents at all. The résumé shows study and work history but is not evidence of admission or of status maintenance.

### Item 6 — Petitioner as a United States employer doing business → FULLY COVERED

`06-corporate-and-organizational-documents.md` answers all four sub-requests: the Delaware certificate of incorporation and the Ohio certificate of good standing dated February 24, 2026 (F-1, F-2); the IRS notice assigning FEIN 47-3319052 (F-3); three years of financial summaries, a filed quarterly wage report for 71 employees, six customer invoices, and a premises lease running to 2030 (F-4); and an organizational chart that places the proffered position within the Automation Engineering group (F-5).

## Notes for test use

- The two partial items fail for different reasons on purpose: item 3 is partial because the evidence stops short in **time and in source** (no end-client voice, no coverage past mid-2027), while item 4 is partial because the evidence stops short in **place** (one worksite covered, a second not).
- Item 4's gap is only discoverable by reading two documents together — the LCA worksite in `01-attorney-cover-letter.md` against the commissioning location in `05-client-services-agreement-and-work-order.md`. A system that checks each document in isolation should be expected to miss it.
- Item 5 is a clean absence: no petition document mentions the subject even in passing.
