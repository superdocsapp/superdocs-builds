# Corpus manifest — `ria-compliance/`

Fictional source material for **Meridian Advisory Services**, a fictional
SEBI-registered investment adviser, used to exercise the compliance pipeline
end to end. All firms, people, dates and figures are invented; the SEBI
requirements they're checked against ([config/requirements.yaml](../config/requirements.yaml))
are real regulation.

Five gaps are planted deliberately so the coverage engine has something real
to find rather than a corpus that trivially passes everything.

## 1. Coverage gap — RIA-REC-01 (records maintained and retrievable)

**No file in this corpus evidences it.** No index, no retention log, no
per-client record inventory exists anywhere in `ria-compliance/`.

[compliance-officer-notes.md](ria-compliance/compliance-officer-notes.md)
names the gap directly ("no single index tying it together per client, and
no one's formally checked we're within the 5-yr window") — but naming the
gap in a note is not evidence of the thing itself. The coverage report must
report RIA-REC-01 as **MISSING**, not treat that note as satisfying it.

## 2. Stale review — CL-01 Ananya Rao, risk profiling

Her only risk profiling questionnaire on file is dated **01/04/22**
([risk-profiling-log.md](ria-compliance/risk-profiling-log.md)), against an
`annual` frequency requirement (RIA-RISK-01). That's several years past due,
also acknowledged in
[client-onboarding-notes.md](ria-compliance/client-onboarding-notes.md) and
[compliance-officer-notes.md](ria-compliance/compliance-officer-notes.md)
("2022 RPQ still the only one on file... still technically overdue"). Her
`risk_profile_reviewed_on` in [config/clients.yaml](../config/clients.yaml)
matches: `2022-04-01`.

(CL-03 Meera Family Trust and CL-07 Sanjay Mehta HUF are *also* stale/absent
in the same log — real registers rarely have exactly one problem — but
CL-01 is the case built to demonstrate this specific behaviour.)

## 3. AI-disclosure gap — CL-06 Priya Nair

`config/clients.yaml` marks her `ai_assisted: true`, and
[client-onboarding-notes.md](ria-compliance/client-onboarding-notes.md)
says AI usage was "discussed" at onboarding — but she has **no entry** in
[ai-usage-register.md](ria-compliance/ai-usage-register.md), unlike CL-02,
CL-04 and CL-08, who each have a dated disclosure and a signed standalone
page on file. The gap is flagged, unresolved, in both the onboarding notes
("need to confirm this went into her file properly") and
[compliance-officer-notes.md](ria-compliance/compliance-officer-notes.md)
("might just be filed wrong, might be an actual gap... \[OPEN — chase
again\]"). RIA-AI-01 evidence for CL-06 does not exist yet.

## 4. Fee inconsistency — CL-02 Vikram Deshmukh

[fee-schedule-change-2026.md](ria-compliance/fee-schedule-change-2026.md)
records his fee moving from **1.2% to 1.5% AUA, effective 01/07/26**
(AUA growth crossed the 50% revision trigger). But
[client-onboarding-notes.md](ria-compliance/client-onboarding-notes.md)'s
most recent entry for him (22/01/25) still shows **1.2% AUA "unchanged"**,
and the fee-change note itself flags this directly: "need to confirm this
is reflected in his client notes / onboarding file — don't think it's been
updated there yet." The two documents disagree on his current fee; RIA-FEE-01
evidence for CL-02 is inconsistent, not simply absent.

## 5. Clean client — CL-04 Kunal Sharma

Every applicable per-client requirement has current, consistent evidence:

| Requirement | Evidence |
|---|---|
| RIA-AGR-01 | Agreement v2 signed 20/01/24 ([client-onboarding-notes.md](ria-compliance/client-onboarding-notes.md)) |
| RIA-RISK-01 | RPQ 18/01/25, redone 20/06/26 — within the annual window ([risk-profiling-log.md](ria-compliance/risk-profiling-log.md), `config/clients.yaml`) |
| RIA-SUIT-01 | Two advice instances, each explicitly linked to the profile in force at the time ([suitability-notes-kunal-sharma.md](ria-compliance/suitability-notes-kunal-sharma.md)) |
| RIA-FEE-01 | 1% AUA, disclosed at onboarding, no revision since, no contradicting figure anywhere |
| RIA-AI-01 | Disclosed 20/01/24, standalone page signed, usage log current ([ai-usage-register.md](ria-compliance/ai-usage-register.md)) |

Confirmed independently in
[compliance-officer-notes.md](ria-compliance/compliance-officer-notes.md):
"one of the tidier ones right now."

Note: his `risk_profile_reviewed_on` was corrected from `2025-01-18` to
`2026-06-20` in `config/clients.yaml` specifically so this client passes an
annual-freshness check against the real current date, not just a plausible
one within the fiction (see the `fix(domain)` commit preceding this corpus).

## Everything else

The remaining clients (CL-03 Meera Family Trust, CL-05 Rohan Textiles,
CL-07 Sanjay Mehta HUF, CL-08 Ishaan Kapoor) and the firm-level net worth
review are ordinary background texture — some thin, one clean onboarding
(CL-08), nothing else deliberately planted beyond what's listed above.
