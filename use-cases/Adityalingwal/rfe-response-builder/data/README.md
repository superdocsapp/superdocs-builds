# Sample case — a fictional H-1B RFE

Everything in this folder is fictional, written for the SuperDocs Round 2
task. No real person, employer, petition, or government notice is involved.
The names, dates, receipt numbers, and addresses are invented.

## The case

- Beneficiary: **Arjun Mehta** (fictional)
- Petitioner/employer: **Brightlayer Analytics Inc.** (fictional)
- Petition: H-1B, Software Engineer (Data Platforms)
- The officer's notice: `notice/rfe-notice-2026-07-30.md`
- The original petition documents: `petition/`

## Why the case is shaped this way

The notice contains **five requests**, spread on purpose across the three
coverage outcomes:

| Request | Topic | Petition coverage | Expected checklist bucket |
|---|---|---|---|
| R1 | Beneficiary's degree and credential evaluation | Fully covered (`04-beneficiary-credentials.md`) | Answered |
| R2 | Specialty occupation | Fully covered (`02-employer-support-letter.md`, `03-job-description.md`) | Answered |
| R3 | Employer-employee relationship | Fully covered (`02-employer-support-letter.md`) | Answered |
| R4 | Availability of specialty work / itinerary | Only a vague mention (`01-cover-letter.md`) | Partially — new evidence needed |
| R5 | Beneficiary's maintenance of status | **Nowhere in the petition** | Not provided — needs attorney confirmation |

R4 and R5 exist so that a run which invents evidence, or which marks
everything "Answered", fails visibly. An honest run must say R5's evidence
is not provided.

## Format note

Files are Markdown. The parser's `.pdf` and `.docx` handling is proven
separately, on the blind cases in `tests/blind/`.
