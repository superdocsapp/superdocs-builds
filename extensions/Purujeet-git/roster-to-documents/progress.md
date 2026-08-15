# Roster → Documents — Project Progress

## Product goal

Build a Google Sheets add-on that turns roster rows into personalized, role-specific documents. The finished product will:

- Read one record per row from Google Sheets.
- Select one of 10 job-family templates based on the job profile, job description, and related fields.
- Use deterministic template rendering for placeholders and conditional sections.
- Use SuperDocs for AI-powered document refinement and document export where appropriate.
- Preview the first three rows before committing to the full batch.
- Generate up to 500 documents in resumable batches.
- Write each generated document link back to the exact source row.
- Send the generated document link to the email address in the row.
- Report row-level failures instead of silently skipping them.

## Confirmed architecture

```text
Google Sheets
    ↓
Google Apps Script
    ├── Sidebar UI
    ├── Spreadsheet read/write
    ├── Drive storage
    ├── Gmail delivery
    ├── Job state / triggers / locking
    └── SuperDocs REST calls
             ↓
        SuperDocs API
             ↓
   AI document refinement/export
```

### Responsibility split

**Google Apps Script**
- Host integration and sidebar.
- Read/write spreadsheet data.
- Store generated files in Google Drive.
- Send email through Gmail.
- Persist batch state.
- Resume jobs with triggers.
- Prevent duplicate workers with locks.

**Our TypeScript code**
- Validate roster data.
- Normalize job-profile values.
- Route rows to the appropriate template.
- Render placeholders.
- Evaluate deterministic conditional sections.
- Keep source row numbers attached to every result.
- Orchestrate document generation and delivery.

**SuperDocs**
- AI-assisted document generation/refinement where it adds value.
- Optional AI fallback for ambiguous routing.
- Document round-trip through the SuperDocs API.
- Final document export.

## Work completed

### Repository / project setup

- [x] Created a self-contained project under `extensions/Purujeet-git/roster-to-documents/`.
- [x] Added project `README.md` with setup and architecture notes.
- [x] Added TypeScript configuration.
- [x] Added `appsscript.json` manifest.
- [x] Added `.gitignore` and `.claspignore`.

### Google Sheets / Apps Script foundation

- [x] Added Apps Script entrypoints and sidebar scaffolding.
- [x] Added active-sheet/roster reading logic.
- [x] Added header-to-row object conversion.
- [x] Preserved the original spreadsheet row number for every record.
- [x] Added batch write-back support for output links and statuses.
- [x] Added configuration for output/link and email columns.

### Template system

- [x] Added a deterministic HTML template renderer.
- [x] Added placeholder replacement using `{{FieldName}}` syntax.
- [x] Added conditional blocks using `{{#if ...}} ... {{/if}}` syntax.
- [x] Kept document structure/attributes intact during rendering.
- [x] Added a template metadata registry.
- [x] Added 10 initial template families:
  - [x] Software Engineer
  - [x] Data / AI
  - [x] Product Manager
  - [x] Sales Executive
  - [x] HR Executive
  - [x] Marketing Executive
  - [x] Finance Analyst
  - [x] Operations Manager
  - [x] Customer Support
  - [x] General / Other

### Routing

- [x] Added deterministic job-profile routing.
- [x] Added aliases for common profile names.
- [x] Added keyword-based fallback matching.
- [x] Added confidence scores and review flags.
- [x] Reserved SuperDocs AI as a fallback for ambiguous cases rather than invoking AI for every row.

### SuperDocs integration

- [x] Added a dedicated SuperDocs API client.
- [x] Added synchronous `POST /v1/chat` support.
- [x] Added asynchronous `POST /v1/chat/async` support.
- [x] Added `GET /v1/jobs/{job_id}` polling support.
- [x] Added `POST /v1/chat/{session_id}/approve` support.
- [x] Added `POST /v1/documents/export` support.
- [x] Designed the integration around HTML-in / HTML-out document processing.
- [x] Kept the SuperDocs API key on the Apps Script server side through script properties.

### Generation / delivery

- [x] Added row-to-document generation orchestration.
- [x] Added Google Drive output handling.
- [x] Added Gmail delivery handling.
- [x] Added separate document, write-back, and email status tracking.

### Batch processing / reliability

- [x] Added resumable job state.
- [x] Added batch processing boundaries for large runs.
- [x] Added Apps Script trigger-based continuation.
- [x] Added concurrency locking with `LockService`.
- [x] Added row-level failure capture.
- [x] Added first-three-row preview flow.

### Testing / validation

- [x] Added unit-test coverage for routing.
- [x] Added unit-test coverage for template rendering.
- [x] Verified the TypeScript project type-checks locally.
- [x] Verified a basic routing/rendering flow locally.
- [x] Added edge-case tests for names, missing fields, conditionals, headers, row slicing, and fallback routing.
- [x] Added automatic sheet-specific template preparation and cached dynamic routing.
- [x] Added trigger cleanup and active-job cancellation.

## Finalized product direction

The final product is intentionally more capable than a single-template mail merge.

### 10-template intelligent routing

The system will maintain a library of 10 approved role-family templates. A row will be routed using this order:

1. Exact job-profile match.
2. Known alias match.
3. Deterministic keyword/metadata match.
4. SuperDocs AI fallback when the profile is genuinely ambiguous.

The AI should return a structured routing result such as:

```json
{
  "templateId": "software-engineer",
  "confidence": 0.94,
  "needsReview": false
}
```

### Deterministic rendering

AI should not be responsible for ordinary placeholder replacement or conditional-section decisions. Those should remain deterministic so that the same row and template produce the same base document.

Example:

```html
<p>Dear {{Name}},</p>

{{#if Department == "Engineering"}}
<p>Engineering Responsibilities</p>
{{/if}}
```

### SuperDocs AI refinement

The generated HTML can optionally be sent to SuperDocs for document refinement. The intended split is:

```text
our renderer → deterministic base document
             ↓
          SuperDocs
             ↓
      proposed/refined document
             ↓
        approve/apply
             ↓
           export
```

Preview mode can use human approval; the confirmed full batch can use an automated approval mode where appropriate.

## Remaining / future work

### Priority 1 — Real Google Apps Script integration

- [ ] Create/configure the real Google Apps Script project with `clasp`.
- [ ] Bind the project to a test Google Sheet.
- [ ] Verify sidebar loading from the actual Sheet.
- [ ] Verify `google.script.run` success/failure handlers.
- [ ] Verify required OAuth scopes from `appsscript.json`.

### Priority 2 — Live SuperDocs verification

- [ ] Add a real SuperDocs API key through Apps Script script properties.
- [ ] Verify the live `/v1/chat` request/response shape against the current API.
- [ ] Verify `/v1/documents/export` and returned binary output.
- [ ] Verify async job polling for long-running operations.
- [ ] Verify approval flow for preview mode.
- [ ] Confirm which operations should use sync versus async calls.
- [ ] Add robust HTTP error parsing and retry/backoff handling.
- [ ] Preserve and validate `data-chunk-id` values through every document round-trip.

### Priority 3 — Template authoring workflow

- [ ] Build the AI-assisted template creation workflow for the 10 job families.
- [ ] Generate first-pass templates with SuperDocs.
- [ ] Review and normalize their structure and placeholder names.
- [ ] Save approved templates as versioned HTML files / Drive artifacts.
- [ ] Add template metadata for aliases, keywords, supported fields, and required fields.
- [ ] Add a path for updating templates without changing the routing code.

### Priority 4 — Intelligent routing improvements

- [ ] Define the final taxonomy for the 10 job families.
- [ ] Expand aliases and deterministic routing rules.
- [ ] Define confidence thresholds.
- [ ] Add manual override for ambiguous classifications.
- [ ] Add an explicit review queue for low-confidence rows.
- [ ] Test routing against a larger realistic roster dataset.

### Priority 5 — Preview UX

- [ ] Make the preview show all three sample rows with selected template, confidence, and status.
- [ ] Show generated document preview information without writing production links back.
- [ ] Clearly identify validation, routing, generation, and email failures.
- [ ] Add a confirmation step before starting the full batch.

### Priority 6 — 500-row production run

- [ ] Determine safe batch size from real execution/quota measurements.
- [ ] Add persisted progress and resume-after-failure behavior.
- [ ] Make reruns idempotent.
- [ ] Decide whether an existing output should be reused, replaced, or skipped.
- [ ] Add retry policy for transient SuperDocs/Google failures.
- [ ] Prevent duplicate documents/emails when a batch resumes.
- [ ] Run a full 500-row test.

### Priority 7 — Failure reporting

- [ ] Add explicit error categories for validation, routing, generation, export, Drive, write-back, and email failures.
- [ ] Add failed-row reporting in the sidebar.
- [ ] Add optional failure details back to a status/error column.
- [ ] Add a retry-failed-rows action.

### Priority 8 — Email and Drive hardening

- [ ] Finalize generated filename conventions.
- [ ] Add configurable Drive output folder.
- [ ] Verify sharing/link permissions match the intended workflow.
- [ ] Add email template configuration.
- [ ] Verify Gmail quotas for realistic batch sizes.
- [ ] Distinguish document success from email success in the UI.

### Priority 9 — Testing

- [ ] Add tests for all 10 route families.
- [ ] Add tests for placeholder escaping and missing fields.
- [ ] Add tests for conditional expressions.
- [ ] Add tests proving row-number/link association cannot drift.
- [ ] Add tests for retries and resumable jobs.
- [ ] Add mock SuperDocs API tests.
- [ ] Add integration tests for a small real Sheet.
- [ ] Add an end-to-end test for the three-row preview.

### Priority 10 — PR readiness

- [ ] Update README with final setup instructions.
- [ ] Document required Google scopes.
- [ ] Document SuperDocs API key setup without exposing secrets.
- [ ] Document local development with `clasp`.
- [ ] Add screenshots / short demo GIF or video if appropriate.
- [ ] Verify no secrets or generated artifacts are committed.
- [ ] Verify files are confined to the project directory.
- [ ] Run final type-check, tests, and build.
- [ ] Prepare the GitHub pull request description.

## Non-goals for v1

The following are intentionally out of scope unless testing proves they are needed:

- A separate FastAPI backend.
- A Next.js frontend.
- A PostgreSQL database.
- Redis or an external job queue.
- A separate authentication server.
- AI generation of every final document from scratch.
- AI-controlled placeholder substitution or business-rule evaluation.
- SSE streaming in the Sheets client.

## Success criteria

The PR should be considered successful when all of the following are demonstrated:

- A user can open the extension from Google Sheets.
- The extension reads a roster correctly.
- The first three rows can be previewed before a full run.
- The correct role template is selected for representative job profiles.
- Placeholders and conditional sections render correctly.
- SuperDocs can refine/process the generated document where configured.
- Documents can be exported and saved to Google Drive.
- The correct document link is written back to the correct row every time.
- Email delivery works for rows containing email addresses.
- A failed row is visibly reported and is not silently skipped.
- A 500-row run can complete through resumable batches without duplicate processing.
- The project remains fully self-contained under the `extensions/<username>/<project>` directory and is ready for a public pull request.
