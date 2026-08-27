# Three-minute demo script

**Target duration:** 3:00. **Hard maximum:** 5:00. If a command is slow, use a pre-recorded offline run and show the captured result; do not wait on a live service.

This script uses only synthetic fixtures. `<SDX_PROJECT>` and `<RRA_PROJECT>` are on-screen labels, not paths to display.

## 0:00–0:20 — The user problem

Show a release manager’s synthetic bundle: requirements, design notes, test evidence, and a release checklist. Narrate: “A release decision is usually spread across documents. The user needs a defensible brief, citations, contradictions, and a human decision gate—not an untraceable summary.”

## 0:20–0:45 — Pipe-friendly document preparation

In a clean terminal, run the verified offline flow:

```text
cat notes.md | sdx new --title "Q3 review" --export pdf
```

Show the non-empty PDF result and a structural validation result. Then show the DOCX variant from the same synthetic source. Say: “`sdx new` accepts stdin, preserves the title, and the offline fixture path verifies PDF and DOCX exports. No live operation is being made.”

## 0:45–1:05 — Review before a change lands

Run `sdx edit` in JSON mode against the synthetic document and show one schema-version-1.0 object with pending changes and exit code 3. Then show the human section-level view: change number/total, heading, change ID, operation, explanation, old text, and new text. Narrate: “JSON never prompts. Human mode makes the proposed sections visible.”

## 1:05–1:25 — Explicit item-level approval

Show a command shaped like:

```text
sdx approve <job-id> --accept ch_1 --reject ch_2 --json
```

Show the validation that every pending change has exactly one decision, followed by the verified export. Narrate: “No proposal lands implicitly; accept, reject, and feedback are explicit per item.” Mask job identifiers if the capture reveals more context than needed.

## 1:25–1:45 — Analyst stages and branches

Switch to the offline Release Readiness Analyst UI or its captured deterministic run. Show six named stages progressing from ingestion and provenance through evidence analysis, policy, review, and report. Show the branch for missing evidence and the contradiction finding. Explain that the files are synthetic fixtures and the run is isolated.

## 1:45–2:05 — Citations, provenance, and hostile text

Open a finding. Point to source name, SHA-256, line range, and quoted evidence. Show a document sentence that says to ignore the review rules; the system labels it untrusted document content rather than following it. Narrate: “The citation is evidence provenance, not a model assertion. Embedded instructions cannot change the policy or tools.”

## 2:05–2:25 — Human decision branch

Show two findings awaiting decisions. Reject one with feedback, approve the other, then show the incomplete-decision guard before submitting the final decision set. Submit the completed set and show the report revision. This demonstrates that a partially approved set remains pending.

## 2:25–2:45 — Interruption and resume

Use the deterministic fault-injection fixture to stop the run after a durable checkpoint. Restart the offline process and resume the same run identifier. Show the stage timeline continuing without creating a replacement run. Say: “This is local restart testing; it does not claim remote cancellation or live recovery.”

## 2:45–2:58 — Incremental evidence

Add one synthetic test-evidence source. Show a new report revision and changed finding IDs while an unaffected finding keeps its identity. Point to the source hash and updated citation. Narrate: “Only invalidated evidence and dependent report sections are recomputed.”

## 2:58–3:00 — Measurable outcome and honest limits

Show a final status card: `sdx` verified export; analyst run `completed`, six stages, three cited findings, all required decisions recorded; policy verdict `blocked` because the synthetic critical findings were intentionally unresolved until the review branch. State on screen: “Offline evidence only; no live calls in this recording; no live cassette; rendered 120-page count unavailable; exact Task 4 PDF wording pending.” End on the report and citation panel, not on a secret-bearing terminal.

### Timing guard

The narration is intentionally shorter than three minutes. Do not add unscripted product claims. If a capture takes longer, cut pauses and use the recorded fixture output; never exceed five minutes.
