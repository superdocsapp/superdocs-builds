# Edit-Quality Rubric and Human-vs-Automated Inter-Rater Agreement Study

*Study run: 2026-08-17T18:12:48.598572+00:00*

## 1. What this study is

This extension scores the quality of SuperDocs document edits against a 6-dimension rubric, then measures agreement between a human judge and an automated LLM judge. The automated judge is a general-purpose LLM (Gemini by default), run blind (instruction + source + edited document, never the human's scores). The point is honest reporting: where the automated judge is unreliable, the report says so.

## 2. Method

**The four-call contract.** Every edit used the SuperDocs minimum contract: `upload` (POST /v1/documents/upload-base64) -> `chat` (POST /v1/chat/async, approval_mode=ask_every_time) -> `approve` (POST /v1/chat/{session}/approve, every proposed change approved atomically) -> `export` (POST /v1/documents/export). Every billable call is in the operation ledger (`data/ledger.jsonl`).

**Rubric.** Six dimensions, ordinal 1-4 with written anchors (see `data/rubric.json`):

- **Faithfulness to instruction** (`faithfulness`) - Did the edit do what the instruction asked, at the scope the instruction implied?
- **Fact accuracy** (`fact_accuracy`) - Did the edit introduce factual errors: wrong dates, numbers, names, amounts, or invented content?
- **Content preservation** (`content_preservation`) - Did the edit preserve untouched content — nothing lost, duplicated, or silently rewritten outside the instruction's scope?
- **Structural integrity** (`structural_integrity`) - Are sections, order, headings, lists, and tables coherent and complete after the edit — no broken numbering, dangling content, or orphaned references?
- **Formatting fidelity** (`formatting_fidelity`) - Did the edit preserve and extend formatting consistently: headings, tables, lists, emphasis — matching the document's existing style?
- **Language quality** (`language_quality`) - Is the edited prose clear, grammatical, and consistent in tone and terminology with the rest of the document?

**Cases.**

| case_id | document | difficulty | instruction |
| --- | --- | --- | --- |
| plan-01 | project_plan | easy | Assign the database migration owner to Dave. |
| plan-02 | project_plan | medium | Add a Milestones section after Section 3 listing the three phases (Backend, API, Frontend) with their dates. |
| plan-03 | project_plan | hard | Rewrite Section 2 (Timeline) to add a 2-day buffer to every date and rename the section to 'Schedule'. |
| plan-04 | project_plan | ambiguous | Make the plan clearer. |
| meeting-01 | meeting_notes | easy | Change the attendee list to include Dave. |
| meeting-02 | meeting_notes | medium | Add a 'Risks' section after the action items that documents the unmitigated database migration delay risk and proposes one mitigation. |
| meeting-03 | meeting_notes | hard | Restructure the notes so decisions come first, action items second, and attendees last. |
| contract-01 | service_contract | easy | Update the pricing table: increase the Business plan monthly fee from $49 to $59. |
| contract-02 | service_contract | medium | Add a 'Data Processing' section after Section 3 with three clauses on GDPR compliance: data ownership, sub-processor approval, and deletion on termination. |
| contract-03 | service_contract | hard | Move Section 4 (Termination) so it comes before Section 3 (Fees and Payment) and renumber all sections and all cross-references. |
| contract-04 | service_contract | ambiguous | Make the contract more tenant-friendly. |

**Judges.**

- **Human** - one human rater, judging from the same before/after material, scoring independently.
- **Automated** - general-purpose LLM, same rubric, blind. A pilot finding: SuperDocs' own chat model is an editing assistant and does not reliably emit JSON scores (see README), so the judge defaults to an external LLM and the token spend is recorded separately.

## 3. Budget guard (stated before the run)

The full-study cap was stated before any run: **60 operations**. Each edit bills 1 operation, so a full run expects ~1 edit operation per case plus any re-runs (re-runs are visible in the ledger below). Automated judging uses a separate external-LLM ledger (`data/ledger_gemini.jsonl`, token spend, 0 SuperDocs operations). Reads, uploads, approvals, and exports bill 0. Every call is recorded in `data/ledger.jsonl`.

## 4. Actual spend

**Spent: 12 operations** (cap 60). Billable calls: 12 of 56 recorded.

| time (UTC) | endpoint | tag | billable | ops | remaining |
| --- | --- | --- | --- | --- | --- |
| 2026-08-17T17:01:33Z |  |  | False | 0 | None |
| 2026-08-17T17:03:04Z |  |  | False | 0 | None |
| 2026-08-17T17:03:21Z | /v1/chat/async (job result) | edit:plan-01 | True | 1 | 498 |
| 2026-08-17T17:03:24Z |  |  | False | 0 | None |
| 2026-08-17T17:03:35Z | /v1/chat/async (job result) | edit:plan-02 | True | 1 | 497 |
| 2026-08-17T17:03:38Z |  |  | False | 0 | None |
| 2026-08-17T17:04:11Z | /v1/chat/async (job result) | edit:plan-03 | True | 1 | 496 |
| 2026-08-17T17:04:15Z |  |  | False | 0 | None |
| 2026-08-17T17:04:44Z | /v1/chat/async (job result) | edit:plan-04 | True | 1 | 495 |
| 2026-08-17T17:04:47Z |  |  | False | 0 | None |
| 2026-08-17T17:05:04Z | /v1/chat/async (job result) | edit:meeting-01 | True | 1 | 494 |
| 2026-08-17T17:05:06Z |  |  | False | 0 | None |
| 2026-08-17T17:05:30Z | /v1/chat/async (job result) | edit:meeting-02 | True | 1 | 493 |
| 2026-08-17T17:06:17Z |  |  | False | 0 | None |
| 2026-08-17T17:06:23Z | /v1/chat/async (job result) | judge:plan-01 | False | 0 | 493 |
| 2026-08-17T17:06:23Z |  |  | False | 0 | None |
| 2026-08-17T17:06:34Z | /v1/chat/async (job result) | judge:plan-02 | False | 0 | 493 |
| 2026-08-17T17:06:35Z |  |  | False | 0 | None |
| 2026-08-17T17:06:57Z | /v1/chat/async (job result) | judge:plan-03 | False | 0 | 493 |
| 2026-08-17T17:06:58Z |  |  | False | 0 | None |
| 2026-08-17T17:07:09Z | /v1/chat/async (job result) | judge:plan-04 | False | 0 | 493 |
| 2026-08-17T17:07:09Z |  |  | False | 0 | None |
| 2026-08-17T17:07:15Z | /v1/chat/async (job result) | judge:meeting-01 | False | 0 | 493 |
| 2026-08-17T17:07:15Z |  |  | False | 0 | None |
| 2026-08-17T17:07:27Z | /v1/chat/async (job result) | judge:meeting-02 | False | 0 | 493 |
| 2026-08-17T17:09:34Z | /v1/chat | chat_sync:eqr_j_plan-01_1786986569 | False | 0 | 493 |
| 2026-08-17T17:09:41Z | /v1/chat | chat_sync:eqr_j_plan-02_1786986574 | False | 0 | 493 |
| 2026-08-17T17:09:46Z | /v1/chat | chat_sync:eqr_j_plan-03_1786986581 | False | 0 | 493 |
| 2026-08-17T17:09:51Z | /v1/chat | chat_sync:eqr_j_plan-04_1786986586 | False | 0 | 493 |
| 2026-08-17T17:09:56Z | /v1/chat | chat_sync:eqr_j_meeting-01_1786986591 | False | 0 | 493 |
| 2026-08-17T17:10:03Z | /v1/chat | chat_sync:eqr_j_meeting-02_1786986596 | False | 0 | 493 |
| 2026-08-17T17:13:49Z | /v1/chat | chat_sync:eqr_j_plan-01_1786986822 | False | 0 | 491 |
| 2026-08-17T17:13:56Z | /v1/chat | chat_sync:eqr_j_plan-02_1786986829 | False | 0 | 491 |
| 2026-08-17T17:14:06Z | /v1/chat | chat_sync:eqr_j_plan-03_1786986836 | False | 0 | 491 |
| 2026-08-17T17:14:13Z | /v1/chat | chat_sync:eqr_j_plan-04_1786986846 | False | 0 | 491 |
| 2026-08-17T17:14:23Z | /v1/chat | chat_sync:eqr_j_meeting-01_1786986853 | False | 0 | 491 |
| 2026-08-17T17:14:29Z | /v1/chat | chat_sync:eqr_j_meeting-02_1786986863 | False | 0 | 491 |
| 2026-08-17T17:15:50Z | /v1/chat | chat_sync:eqr_j_plan-01_1786986944 | False | 0 | 491 |
| 2026-08-17T17:15:57Z | /v1/chat | chat_sync:eqr_j_plan-02_1786986950 | False | 0 | 491 |
| 2026-08-17T17:16:01Z | /v1/chat | chat_sync:eqr_j_plan-03_1786986957 | False | 0 | 491 |
| 2026-08-17T17:16:07Z | /v1/chat | chat_sync:eqr_j_plan-04_1786986961 | False | 0 | 491 |
| 2026-08-17T17:16:13Z | /v1/chat | chat_sync:eqr_j_meeting-01_1786986967 | False | 0 | 491 |
| 2026-08-17T17:16:25Z | /v1/chat | chat_sync:eqr_j_meeting-02_1786986973 | False | 0 | 491 |
| 2026-08-17T17:20:44Z |  |  | False | 0 | None |
| 2026-08-17T17:21:19Z | /v1/chat/async (job result) | edit:plan-04 | True | 1 | 490 |
| 2026-08-17T17:21:21Z |  |  | False | 0 | None |
| 2026-08-17T17:21:49Z | /v1/chat/async (job result) | edit:meeting-03 | True | 1 | 489 |
| 2026-08-17T17:21:52Z |  |  | False | 0 | None |
| 2026-08-17T17:22:14Z | /v1/chat/async (job result) | edit:contract-01 | True | 1 | 488 |
| 2026-08-17T17:22:17Z |  |  | False | 0 | None |
| 2026-08-17T17:23:25Z |  |  | False | 0 | None |
| 2026-08-17T17:23:58Z | /v1/chat/async (job result) | edit:contract-03 | True | 1 | 487 |
| 2026-08-17T17:24:44Z |  |  | False | 0 | None |
| 2026-08-17T17:25:18Z | /v1/chat/async (job result) | edit:contract-02 | True | 1 | 486 |
| 2026-08-17T17:29:44Z |  |  | False | 0 | None |
| 2026-08-17T17:30:13Z | /v1/chat/async (job result) | edit:contract-04 | True | 1 | 485 |

## 5. Scores

Human and automated scores per case and dimension (1=Fail ... 4=Excellent):

| case | difficulty | dim | human | auto | diff |
| --- | --- | --- | --- | --- | --- |
| plan-01 | easy | (total) | 24/24 | 24/24 | |
| plan-01 | | faithfulness | 4 | 4 | +0 |
| plan-01 | | fact_accuracy | 4 | 4 | +0 |
| plan-01 | | content_preservation | 4 | 4 | +0 |
| plan-01 | | structural_integrity | 4 | 4 | +0 |
| plan-01 | | formatting_fidelity | 4 | 4 | +0 |
| plan-01 | | language_quality | 4 | 4 | +0 |
| plan-02 | medium | (total) | 18/24 | 21/24 | |
| plan-02 | | faithfulness | 1 | 1 | +0 |
| plan-02 | | fact_accuracy | 1 | 4 | -3 |
| plan-02 | | content_preservation | 4 | 4 | +0 |
| plan-02 | | structural_integrity | 4 | 4 | +0 |
| plan-02 | | formatting_fidelity | 4 | 4 | +0 |
| plan-02 | | language_quality | 4 | 4 | +0 |
| plan-03 | hard | (total) | 22/24 | 20/24 | |
| plan-03 | | faithfulness | 2 | 2 | +0 |
| plan-03 | | fact_accuracy | 4 | 2 | +2 |
| plan-03 | | content_preservation | 4 | 4 | +0 |
| plan-03 | | structural_integrity | 4 | 4 | +0 |
| plan-03 | | formatting_fidelity | 4 | 4 | +0 |
| plan-03 | | language_quality | 4 | 4 | +0 |
| plan-04 | ambiguous | (total) | 18/24 | 24/24 | |
| plan-04 | | faithfulness | 4 | 4 | +0 |
| plan-04 | | fact_accuracy | 4 | 4 | +0 |
| plan-04 | | content_preservation | 4 | 4 | +0 |
| plan-04 | | structural_integrity | 1 | 4 | -3 |
| plan-04 | | formatting_fidelity | 1 | 4 | -3 |
| plan-04 | | language_quality | 4 | 4 | +0 |
| meeting-01 | easy | (total) | 24/24 | 24/24 | |
| meeting-01 | | faithfulness | 4 | 4 | +0 |
| meeting-01 | | fact_accuracy | 4 | 4 | +0 |
| meeting-01 | | content_preservation | 4 | 4 | +0 |
| meeting-01 | | structural_integrity | 4 | 4 | +0 |
| meeting-01 | | formatting_fidelity | 4 | 4 | +0 |
| meeting-01 | | language_quality | 4 | 4 | +0 |
| meeting-02 | medium | (total) | 18/24 | 21/24 | |
| meeting-02 | | faithfulness | 2 | 2 | +0 |
| meeting-02 | | fact_accuracy | 3 | 4 | -1 |
| meeting-02 | | content_preservation | 4 | 4 | +0 |
| meeting-02 | | structural_integrity | 2 | 3 | -1 |
| meeting-02 | | formatting_fidelity | 3 | 4 | -1 |
| meeting-02 | | language_quality | 4 | 4 | +0 |
| meeting-03 | hard | (total) | 19/24 | 22/24 | |
| meeting-03 | | faithfulness | 1 | 2 | -1 |
| meeting-03 | | fact_accuracy | 4 | 4 | +0 |
| meeting-03 | | content_preservation | 4 | 4 | +0 |
| meeting-03 | | structural_integrity | 2 | 4 | -2 |
| meeting-03 | | formatting_fidelity | 4 | 4 | +0 |
| meeting-03 | | language_quality | 4 | 4 | +0 |
| contract-01 | easy | (total) | 24/24 | 21/24 | |
| contract-01 | | faithfulness | 4 | 1 | +3 |
| contract-01 | | fact_accuracy | 4 | 4 | +0 |
| contract-01 | | content_preservation | 4 | 4 | +0 |
| contract-01 | | structural_integrity | 4 | 4 | +0 |
| contract-01 | | formatting_fidelity | 4 | 4 | +0 |
| contract-01 | | language_quality | 4 | 4 | +0 |
| contract-02 | medium | (total) | 24/24 | 23/24 | |
| contract-02 | | faithfulness | 4 | 4 | +0 |
| contract-02 | | fact_accuracy | 4 | 4 | +0 |
| contract-02 | | content_preservation | 4 | 4 | +0 |
| contract-02 | | structural_integrity | 4 | 3 | +1 |
| contract-02 | | formatting_fidelity | 4 | 4 | +0 |
| contract-02 | | language_quality | 4 | 4 | +0 |
| contract-03 | hard | (total) | 24/24 | 24/24 | |
| contract-03 | | faithfulness | 4 | 4 | +0 |
| contract-03 | | fact_accuracy | 4 | 4 | +0 |
| contract-03 | | content_preservation | 4 | 4 | +0 |
| contract-03 | | structural_integrity | 4 | 4 | +0 |
| contract-03 | | formatting_fidelity | 4 | 4 | +0 |
| contract-03 | | language_quality | 4 | 4 | +0 |
| contract-04 | ambiguous | (total) | 15/24 | 18/24 | |
| contract-04 | | faithfulness | 3 | 4 | -1 |
| contract-04 | | fact_accuracy | 4 | 2 | +2 |
| contract-04 | | content_preservation | 1 | 3 | -2 |
| contract-04 | | structural_integrity | 1 | 2 | -1 |
| contract-04 | | formatting_fidelity | 3 | 4 | -1 |
| contract-04 | | language_quality | 3 | 3 | +0 |

## 6. Inter-rater agreement (human vs automated)

**Overall:** percent exact agreement 75.8% over 66 judgments (11 cases x 6 dimensions); Cohen's kappa **0.339** (95% CI [0.126, 0.541]); linear-weighted kappa **0.405**.

Per dimension:

| dimension | n | % exact | kappa | kappa 95% CI | band | weighted kappa |
| --- | --- | --- | --- | --- | --- | --- |
| Faithfulness to instruction | 11 | 72.7% | 0.56 | [0.096, 1.0] | moderate | 0.645 |
| Fact accuracy | 11 | 63.6% | -0.1 | [-0.185, 0.0] | poor | -0.158 |
| Content preservation | 11 | 90.9% | 0.476 | [0.421, 1.0] | moderate | 0.476 |
| Structural integrity | 11 | 54.5% | 0.127 | [-0.112, 0.389] | slight | 0.279 |
| Formatting fidelity | 11 | 72.7% | 0.0 | [0.0, 1.0] | slight | 0.0 |
| Language quality | 11 | 100.0% | 1.0 | [1.0, 1.0] | almost perfect | 1.0 |

Score distribution per rater (count of 1-4 judgments):

| score | human | auto |
| --- | --- | --- |
| 1 | 7 | 2 |
| 2 | 4 | 6 |
| 3 | 5 | 4 |
| 4 | 50 | 54 |

Confusion matrices per dimension (rows = human, columns = automated; diagonal cells are exact agreements):

**Faithfulness to instruction** (`faithfulness`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 1 | 1 | 0 | 0 |
| 2 | 0 | 2 | 0 | 0 |
| 3 | 0 | 0 | 0 | 1 |
| 4 | 1 | 0 | 0 | 5 |

**Fact accuracy** (`fact_accuracy`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 0 | 1 |
| 2 | 0 | 0 | 0 | 0 |
| 3 | 0 | 0 | 0 | 1 |
| 4 | 0 | 2 | 0 | 7 |

**Content preservation** (`content_preservation`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 1 | 0 |
| 2 | 0 | 0 | 0 | 0 |
| 3 | 0 | 0 | 0 | 0 |
| 4 | 0 | 0 | 0 | 10 |

**Structural integrity** (`structural_integrity`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 1 | 0 | 1 |
| 2 | 0 | 0 | 1 | 1 |
| 3 | 0 | 0 | 0 | 0 |
| 4 | 0 | 0 | 1 | 6 |

**Formatting fidelity** (`formatting_fidelity`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 0 | 1 |
| 2 | 0 | 0 | 0 | 0 |
| 3 | 0 | 0 | 0 | 2 |
| 4 | 0 | 0 | 0 | 8 |

**Language quality** (`language_quality`)

| human \ auto | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1 | 0 | 0 | 0 | 0 |
| 2 | 0 | 0 | 0 | 0 |
| 3 | 0 | 0 | 1 | 0 |
| 4 | 0 | 0 | 0 | 10 |


## 7. Disagreement review (where the automated judge is unreliable)

8 judgments disagreed by 2+ scale points. Each row cites both raters' evidence.

### contract-01 / `faithfulness` - human 4 vs auto 1 (diff +3)
*Difficulty: easy*
- Instruction: Update the pricing table: increase the Business plan monthly fee from $49 to $59.
- Human evidence: 
- Auto evidence: The edited document is identical to the source document; the instruction to update the Business plan monthly fee from $49 to $59 was ignored.

### plan-02 / `fact_accuracy` - human 1 vs auto 4 (diff -3)
*Difficulty: medium*
- Instruction: Add a Milestones section after Section 3 listing the three phases (Backend, API, Frontend) with their dates.
- Human evidence: 
- Auto evidence: No factual errors were introduced into the text.

### plan-04 / `structural_integrity` - human 1 vs auto 4 (diff -3)
*Difficulty: ambiguous*
- Instruction: Make the plan clearer.
- Human evidence: Headings were changed
- Auto evidence: The overall document structure and section order remain completely intact.

### plan-04 / `formatting_fidelity` - human 1 vs auto 4 (diff -3)
*Difficulty: ambiguous*
- Instruction: Make the plan clearer.
- Human evidence: In section 3, it used inconsistent formatting
- Auto evidence: Markdown list structure and basic formatting are preserved and clear throughout.

### contract-04 / `fact_accuracy` - human 4 vs auto 2 (diff +2)
*Difficulty: ambiguous*
- Instruction: Make the contract more tenant-friendly.
- Human evidence: 
- Auto evidence: Introduced direct internal contradictions regarding timeline facts: Section 2.1 requires 30 days' notice for non-renewal while Section 2.2 specifies 60 days; Section 3.1 sets payment due date at 30 days post-receipt while Section 3.2 keeps the 14-day limit.

### contract-04 / `content_preservation` - human 1 vs auto 3 (diff -2)
*Difficulty: ambiguous*
- Instruction: Make the contract more tenant-friendly.
- Human evidence: 
- Auto evidence: Rather than editing existing clauses cleanly, the edit retained conflicting original statements alongside new additions (e.g., leaving Section 3.2 intact while adding conflicting payment terms to Section 3.1).

### meeting-03 / `structural_integrity` - human 2 vs auto 4 (diff -2)
*Difficulty: hard*
- Instruction: Restructure the notes so decisions come first, action items second, and attendees last.
- Human evidence: 
- Auto evidence: The document structure is clean and coherent without broken elements.

### plan-03 / `fact_accuracy` - human 4 vs auto 2 (diff +2)
*Difficulty: hard*
- Instruction: Rewrite Section 2 (Timeline) to add a 2-day buffer to every date and rename the section to 'Schedule'.
- Human evidence: 
- Auto evidence: The dates were not shifted by 2 days as required (August 10, 20, and September 05 remained unadjusted instead of August 12, 22, and September 07).

## 8. Honest limitations

- **Small sample.** This is a small-sample study by design (budget guard first). Kappa 95% CIs are wide and must not be read as precise estimates.
- **Single human rater.** Agreement here is human-1 vs auto, not a gold standard; human-human agreement would need a second rater.
- **Sparse human evidence.** The human rater recorded written evidence for only a few dimensions (plan-04); most disagreement rows therefore carry only the automated judge's evidence. Score differences are still reviewable from the before/after material in `data/edits/`.
- **Ordinal scale ceiling.** Dimensions on which every case scores 3-4 (or 1-2) compress kappa even when raters agree on ranking; weighted kappa partially compensates.
- **Blindness limits.** The automated judge sees text; visual formatting regressions in the final rendered file may not be visible to it - treated honestly per dimension in the evidence.

## 9. Reproduce

```bash
pip install -r requirements.txt
python scripts/run_study.py --small   # or --full; cap enforced in app/budget.py
uvicorn app.main:app                   # judge UI at /judge, report at /report
```

Every artifact is on disk: `data/edits/<case_id>/` (upload, pending changes, approve, job result, before/after HTML, exported docx) and `data/judgments/` (score sheets).