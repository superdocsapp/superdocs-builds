# Progress

## Phase 1 — complete

Implemented the deterministic PolicySet domain core for one fictional store, Northstar Goods:

- Four managed documents: `terms`, `privacy`, `warranty`, `returns`
- Canonical `PolicyProfile` (~25 fields) covering company, store, returns, warranty, and privacy facts
- Explicit TypeScript dependency registry from managed field paths to affected documents
- `ChangeSet` with `pending` / `proposed` / `approved` / `rejected` / `failed`
- Transaction functions: create does not mutate the profile; reject and fail do not mutate the profile; commit is allowed only for an approved changeset and returns a new profile
- Deterministic HTML renderers driven only by `PolicyProfile`, each including `drafted for attorney review, not legal advice`
- Consistency validator with structured issues (missing document/disclaimer, company/contact/date mismatches, return-window and warranty-duration disagreements, stale return window after commit)

No SuperDocs calls. No editor UI.

## Phase 2 — complete

Turned the Phase 1 profile/renderers into real DOCX files and added a small server-side SuperDocs adapter.

- `generatePolicyDocuments(profile)` emits exactly four DOCX files from the same PolicyProfile
- Each file has a document title, effective date, company/contact facts, and that document's managed facts
- The attorney-review disclaimer is a real Word footer, not a body paragraph
- SuperDocs adapter covers caller-generated session ids, upload (`replace` / `background`), roster GET with `include_html`, focus, async chat with optional `document_id`, job polling, approve/deny, and focus-then-export for DOCX/PDF
- `SUPERDOCS_API_KEY` is server-side only; `.env.example` documents it
- Local preview script writes Northstar DOCX files to `tmp/policyset-preview/`; `--upload` is opt-in and does not start chat

No HITL. No synchronized ChangeSet execution. No live SuperDocs call was made during this phase.

## Phase 3 — complete

Built the user-facing intake → generate → four-document workspace flow. Frontend/product UI only.

- Guided intake on `/` with four sections (Company, Store, Returns & Warranty, Privacy), prefilled from the Northstar Goods fixture
- Generate Policy Set builds a `PolicyProfile`, runs the deterministic HTML renderers, validates the set, and opens the workspace
- Workspace shows Policy Set name, company name, consistency status, four document tabs, a document-style preview surface, and a read-only Policy Facts panel sourced from `PolicyProfile`
- Preview is explicitly a deterministic HTML surface, not SuperDocs
- Local React state only; localStorage was deferred because it complicated hydration/lint

No SuperDocs browser calls. No AI editing/HITL. No ChangeSet execution. No export.

## Phase 4 — complete

Connected the Phase 3 workspace to real, server-side SuperDocs editing with
single-document human review.

- Workspace initializes one caller-generated SuperDocs session from the current
  `PolicyProfile`, uploading Terms as `replace` and Privacy, Warranty, and Returns
  as `background`, then retains the session id and four document-id mapping in
  workspace state
- Focused Next.js route handlers cover session initialization/refresh, pinned
  edit start, async job polling, and review submission; the API key and production
  adapter remain server-only
- Every edit uses the selected tab's `document_id` with `approval_mode=ask_every_time`
  and `response_mode=full`
- Async UI covers idle, submitting, processing, awaiting review, applying,
  completed, and error states
- Review shows document, explanation, before, and after, and approves or rejects
  the full single-document batch with one explicit decision per `change_id`
- Proposal polling and review both fail closed if any pending change targets a
  document other than the selected document
- Approval polls to completion, refreshes the authoritative session roster with
  HTML, and replaces only the selected workspace document; rejection leaves the
  displayed documents and canonical profile unchanged
- Generic AI edits are explicitly language-only; no SuperDocs edit is inferred
  back into the canonical `PolicyProfile`

### Phase 4 live validation

Ran one paid edit for Northstar Goods against the Warranty document:

> Make the warranty claim instructions clearer and more concise without changing
> the warranty duration.

- Job reached `awaiting_approval` with one proposal, and its `document_id` matched
  the stored Warranty id
- The proposal rewrote the claim instruction from two sentences into one clearer,
  concise filing instruction; the explicit approval receipt covered one change
- Authoritative post-completion HTML changed for Warranty only
- The 12-month warranty value remained present
- Terms, Privacy, and Returns HTML retained identical pre/post SHA-256 hashes
- Rough edge: the first initialization attempt encountered a transient upload
  transport failure reported as `SuperDocs is unavailable`; it occurred before
  any paid chat operation, and a safe retry initialized and completed normally

## Phase 5 — implementation complete; three live runs, all failed closed

Implemented the synchronized managed-fact ChangeSet workflow for the return
window (`returns.windowDays`):

- The Policy Facts panel exposes only Return window as editable and creates the
  existing immutable ChangeSet transaction; the dependency registry resolves
  the affected set to Terms and Returns
- The current SuperDocs session is reused when present; immediately before chat,
  PolicySet retrieves the authoritative four-document roster with
  `include_html=true` and captures normalized content plus SHA-256 for every
  document
- One unpinned multi-document chat job is started with
  `approval_mode=ask_every_time` and `response_mode=full`; its instruction is
  constructed from the ChangeSet affected set and explicitly protects
  unaffected documents, unrelated terms, headers, and footers
- The proposal gate maps every `document_id` through the workspace document map,
  requires exact affected-set coverage, validates the 30-day to 14-day content
  transition, and rejects create/delete or header/footer changes
- A polluted or protected-content proposal batch is failed closed by explicitly
  denying every pending `change_id`; rejection also denies every pending change
  and leaves the canonical profile and workspace documents unchanged
- Review proposals are grouped by PolicySet document and show the canonical
  30-to-14 fact transition, before/after content, and explanations
- After approval, PolicySet waits for completion, retrieves the authoritative
  four-document roster, verifies Terms/Returns managed values, checks all four
  documents with the consistency validator, and compares normalized hashes for
  untouched documents
- Only successful post-edit validation calls the existing ChangeSet commit
  function, which returns a new PolicyProfile; every earlier failure path leaves
  the canonical return window at 30

### Phase 5 live validation

Ran exactly one paid Northstar Goods 30-day to 14-day operation:

- ChangeSet visibly resolved affected documents to Terms and Returns
- One unpinned SuperDocs job was started; no `document_id` was sent
- Authoritative pre-edit hashes were captured for all four documents
- SuperDocs returned a proposal batch that the safety gate classified as
  touching header/footer content
- PolicySet explicitly denied every pending change and returned an actionable
  safety error; no prompt retry or second paid operation was attempted
- The post-denial authoritative normalized hashes exactly matched pre-edit for
  all four documents:
  - Terms: `dc2ee338d27c4d9622b1609d51bef405daa3a4fdeea957dab4dcc147f211644a`
  - Privacy: `2015ee8534e9c181ae7921221a8fb8a04d2bbdaa56684e0a5de70419764b00e4`
  - Warranty: `e2434ca945c21bb9aa50f11b8494a43588e57f2b6e58033c62f57b700e2a2ec6`
  - Returns: `4a0bb6f1d4f00d70c80cbbbfb01a515d9ed0ae3e4b2761ccbba3c2ebbdccfca4`
- Terms and Returns therefore remained at 30 days, Privacy and Warranty were
  unchanged, and the canonical PolicyProfile remained 30; approval,
  post-approval validation, and canonical commit were intentionally not reached

SuperDocs rough edge: after an explicitly denied batch reaches `completed`, its
job snapshot no longer exposes `pending_changes`, so the exact protected fragment
cannot be re-inspected after denial. No second operation was spent reproducing
it.

### Phase 5 proposal-evidence repair

- The first-run classifier concatenated `chunk_id`, `old_html`, and `new_html`
  and treated any header/footer word, any `<h1>`, or the disclaimer anywhere in
  that combined content as protected targeting. This was an overly broad
  classifier capable of false positives from surrounding full-document HTML.
- The exact matching branch for the already-denied live batch is unrecoverable
  because the old implementation did not retain branch-level evidence and
  SuperDocs removed `pending_changes` after denial. The prior batch therefore
  cannot honestly be classified as a genuine header/footer edit or a confirmed
  false positive.
- Pending proposals are now persisted to an ignored local evidence directory
  before any approve or deny decision. Snapshots contain only the requested
  proposal fields plus local classification/reason, redact secret-shaped values,
  use hashed filenames, and are written with restrictive permissions.
- Header/footer classification now requires structural targeting evidence: a
  known header/footer `chunk_id`, a root structural part marker, or structural
  metadata on the element matching the targeted chunk. Disclaimer text, `<h1>`,
  and nested surrounding footer HTML do not classify a body proposal as unsafe.
- The gate remains fail-closed for structurally identified header/footer
  proposals and when evidence persistence fails. No additional live SuperDocs
  operation was run for this repair.

### Phase 5 second live validation — partial edit within targeted documents

A second paid Northstar Goods 30-to-14 operation, after the repaired
classifier:

- The proposal gate correctly resolved and targeted only Terms and Returns;
  no header/footer or Privacy/Warranty proposal was returned
- Within Terms, only the managed fact label moved 30 → 14; the body prose
  ("30-day window") stayed at 30
- Within Returns, only the body prose moved 30 → 14; the managed fact label
  stayed at 30
- Post-approval validation (`validatePolicySet` / `validateReturnWindowTransition`)
  correctly detected both stale-30 and transition-incomplete issues and
  blocked canonical commit; `returns.windowDays` remained 30
- Evidence: `tmp/policyset-proposal-evidence/proposal-6fbda40bad603df29ff64314.json`,
  `tmp/phase5-final-live-report.json` (superseded by the third run, see below)

This showed the targeting gate (which documents) was sound but exposed a real
gap: nothing checked whether a proposal batch updated *every* required
occurrence of the managed fact inside a targeted document, only whether the
value transitioned somewhere.

### Managed-fact coverage gate

Added the smallest mechanism that closes that gap, scoped to
`returns.windowDays` only:

- `src/domain/managed-occurrences.ts` — an explicit, hand-written occurrence
  model (no extraction engine, no RAG/embeddings/LLM): three regex patterns
  (`fact-label`, `prose-delivery-window`, `prose-window-crossref`) matched
  against `data-chunk-id`-split authoritative SuperDocs HTML, excluding
  header/footer chunks. `RETURN_WINDOW_COVERAGE_MODEL` states that Terms and
  Returns must each yield a `fact_label` and a `policy_prose` occurrence.
- `src/superdocs/managed-coverage.ts` — `evaluateReturnWindowCoverage()`
  matches each required occurrence to a proposal by `(document_id, chunk_id)`
  and checks the proposed `new_html` actually moves that occurrence from the
  previous value to the next with no stale previous value left; it also flags
  any proposal targeting a chunk that holds no required occurrence.
- `assertSynchronizedProposalGate()` in `src/superdocs/policyset.ts` now runs
  both halves before any approval: targeting safety (existing) and
  completeness (new). Both the proposal-polling path and the approval path of
  `submitPolicySynchronizedReview` deny every pending `change_id` and fail
  closed if either half fails; the canonical profile is never touched.
- The synchronized-edit instruction now names both required shapes explicitly
  ("Return window (days) summary fact line" and the two body-prose forms) and
  states the fact must not remain anywhere in the affected documents, in
  addition to the existing protections for unaffected documents, unrelated
  terms, and headers/footers.
- Five focused tests were added to `tests/phase5.test.ts`: partial Terms
  coverage rejected, partial Returns coverage rejected, full coverage in both
  documents passes, polluted targeting still fails closed even with full
  coverage, and incomplete coverage denies every `change_id` while the
  canonical profile stays at 30. `npm test` (52 passed), `npm run typecheck`,
  `npm run lint`, and `npm run build` all pass.

### Phase 5 third (final) live validation — failed closed

Ran exactly one more paid Northstar Goods 30-to-14 operation against a fresh
session, with both gates active:

- Session `policyset-e9a8e757-3be0-40eb-928d-bce5f45c2568`, job
  `5e5c9da0-3a45-40a7-bb3a-6325082bc5b9`
- SuperDocs returned 26 proposals, all against Terms (`doc_primary`); zero
  proposals against Returns despite the instruction naming it explicitly
- Of the 26 Terms proposals, only 2 contained an actual content change and
  both were correct (fact label and body prose, 30 → 14); the other 24 had
  byte-identical `old_html`/`new_html` — no-op "edit" proposals — two of
  which targeted the document's header and footer chunks
- The targeting gate failed (header/footer structurally identified) and the
  coverage gate failed (Returns had zero required occurrences covered); every
  pending `change_id` was explicitly denied, no approval was ever submitted
- Post-denial authoritative state: Terms still only contains 30-day return
  window content, Returns unchanged, Privacy/Warranty SHA-256 unchanged from
  pre-edit; `returns.windowDays` remained 30; ChangeSet ended `rejected`
- Full detail, reproduction steps, and classification:
  `tmp/phase5-final-live-issue-report.md` (gitignored local evidence,
  alongside `tmp/phase5-final-live-report.json` and
  `tmp/policyset-proposal-evidence/proposal-296d8852c930967662b3364b.json`)

Classification (see the issue report for full reasoning):
- Unpinned chat editing only one of two named documents: **SUPERDOCS_ROUGH_EDGE**
  / possible bug, low-moderate confidence — the prior live run *did* touch
  both documents from an equivalent unpinned request, so this reads as
  nondeterministic scope rather than a fixed, documented limitation. **Do not
  report as confirmed bug yet.**
- 24 of 26 "edit" proposals with byte-identical old/new HTML, two against
  protected structural chunks: **CONFIRMED_SUPERDOCS_BUG** by direct artifact
  evidence (single job only). **Recommended to report to SuperDocs.**

No further paid operation was run. Phase 6 was not started.

Both findings from the three live runs above are written up, sanitized for a
public/hiring-round audience, in [`SUPERDOCS_ISSUES.md`](./SUPERDOCS_ISSUES.md).

### Phase 5 reliability fallback — explicit targeted jobs

The three live runs above converged on one conclusion: an unpinned,
multi-document SuperDocs chat job is not reliable enough for production
PolicySet synchronization (nondeterministic document scope; a padded batch of
no-op proposals in the one run that did stay in scope). Rather than keep
retrying the unpinned approach, the synchronized ChangeSet execution strategy
was replaced. The user-facing operation is unchanged — one "Propose
synchronized update" action still moves the return window from 30 to 14 across
Terms and Returns, reviewed and approved/rejected as one synchronized batch.

- `startPolicySynchronizedEdit` no longer sends one unpinned `chat/async`
  call. It starts one explicit, `document_id`-pinned `chat/async` job per
  document in `changeSet.affectedDocuments` (still resolved from
  `DEPENDENCY_REGISTRY` via `getAffectedDocuments`, never hardcoded), each
  with `approval_mode=ask_every_time` and its own single-document instruction
  built by `buildTargetedSynchronizedInstruction`.
- `getPolicyTargetedSynchronizedJob` polls one targeted job. The moment that
  job reaches `awaiting_approval` with proposals, it runs that document's own
  targeting-safety and managed-fact-coverage gate (`assertTargetedProposalGate`,
  which narrows the existing `assertSynchronizedProposalSafety` /
  `assertSynchronizedProposalCoverage` checks to that one document) before the
  batch is treated as reviewable. A gate failure denies every pending change
  on that job.
- The client (`WorkspaceView`) polls every targeted job concurrently. Once
  every job has independently reached `awaiting_approval` with a passing
  gate, PolicySet shows one unified review grouped by document — the reviewer
  never has to know two separate SuperDocs jobs exist. If any job's gate
  fails (or the job itself fails), PolicySet explicitly denies every pending
  change on every *other* job that had already reached a passing
  `awaiting_approval` state, marks the ChangeSet failed, names which document
  failed, and does not retry automatically.
- Rejecting the unified review denies every pending `change_id` on every
  targeted job. Approving submits an explicit approval for every validated
  `change_id` on every targeted job, then polls every job to `completed`
  before doing anything else.
- Two SuperDocs jobs are not one atomic provider transaction. If approval
  submission or completion polling fails for one job after succeeding for the
  other, PolicySet does not commit the canonical PolicyProfile, marks the
  ChangeSet failed, and surfaces that document state may need recovery — it
  does not attempt a rollback or an automatic compensating operation. As a
  second line of defense, `commitValidatedSynchronizedChange`'s existing
  post-edit validation (authoritative Terms/Returns transition check, stale-30
  detection, Privacy/Warranty hash comparison) would independently block
  commit even if a partial-apply state were reached without the orchestration
  noticing, since it re-reads the authoritative four-document roster rather
  than trusting job-completion status alone.
- No-op proposals (`old_html === new_html`) are not explicitly special-cased;
  they fail the existing gates on their own merits — a no-op can never
  satisfy a required occurrence's before→after transition, and a no-op
  targeting a chunk outside the required set is flagged as an unexpected
  chunk, so the batch containing it is denied.
- Eight focused tests cover: affected documents resolved from the dependency
  registry; two explicit pinned jobs started (not one unpinned job); a
  targeted job's own gate failing closed and denying that job's pending
  changes on a polluted or incomplete batch; per-job rejection denying that
  job's pending changes; a full two-document validated commit reaching 14;
  partial apply (one document's authoritative content never actually changed)
  blocking commit and leaving the profile at 30; and a no-op proposal failing
  to satisfy coverage even when every real required occurrence is otherwise
  covered. `npm test` (56 passed), `npm run typecheck`, `npm run lint`, and
  `npm run build` all pass.
- No live SuperDocs call was made for this fallback. The old Phase 5 live
  validation driver script (`tmp/phase5-final-live-validation.ts`) targets the
  retired unpinned-job API and was left as-is (git-ignored local tooling, not
  evidence); `tmp` was added to `tsconfig.json`'s `exclude` so that obsolete
  script does not block `typecheck`/`build`. A new driver script for the
  targeted-job flow would be needed before running a live fallback test.

### Phase 5 targeted-job live run — failed before either job was usable

The targeted-job fallback was run live once. It failed at job start, before
any proposal existed. Both jobs reported `jobId: null` / `gate: NOT_REACHED`,
the canonical profile stayed at 30, and the ChangeSet was marked failed.

Investigation findings (no live call made during the investigation):

- **The two pinned starts were sequential, not concurrent.**
  `startPolicySynchronizedEdit` uses a `for…of` loop with `await` inside;
  `Promise.allSettled` in the driver applies only to polling. Terms is
  attempted first (`POLICY_DOCUMENT_TYPES` order), Returns immediately after.
  The two requests are therefore sequential but temporally overlapping: the
  Returns start races the Terms job's `pending`/`in_progress` phase.
- The observed message `SuperDocs rejected the operation for the current job
  state` is emitted at exactly one place in the adapter — the **HTTP 409**
  branch of `statusError`. High confidence, but inferred from our own string
  mapping rather than read from a captured response.
- **Likely cause: a session-level job-in-flight restriction.** The session was
  fresh with only uploads on it, so there was nothing for the *first* start to
  conflict with; the 409 almost certainly came from the second start.
- **This restriction is not documented for `chat/async` in the local
  references.** `openapi-live.json` lists only 200/422 for
  `POST /v1/chat/async`. A session-level in-flight lock *is* documented, but
  only for revert/redo (which do 409 while a job is `pending`, `in_progress`,
  or `awaiting_approval`). `document_id` targeting itself is documented and
  was already live-validated in Phase 4. Current classification:
  **UNDOCUMENTED_SUPERDOCS_LIMITATION, moderate confidence** — one
  observation, not yet strengthened.
- **The previous live report lost the provider error body and request id.**
  The adapter read the response bytes and then discarded them on the error
  path, and the driver recorded only `error.message`.
- **The previous `paidOperationsUsed: 0` was not provider-confirmed.** It was
  assigned only after the whole batch succeeded, so the throw left the
  initializer in place. Actual usage was most likely 1 paid Terms chat start.
  SuperDocs returns no usage metadata, so no count of ours can be called
  provider-confirmed.

Instrumentation is being repaired before another live test, rather than
re-running the same experiment blind:

- `SuperDocsRequestError` now carries `providerCode` and `providerDetail`
  alongside `statusCode`/`requestId`, exposed through `diagnostics()`. Only a
  machine-readable code and a short, redacted, length-bounded message are kept
  from JSON error bodies; non-JSON bodies (HTML error pages) contribute
  nothing, and no headers or credentials are ever retained. Friendly
  application messages are unchanged.
- `startPolicySynchronizedEdit` now throws `PolicySetSynchronizedStartError`
  when a later pinned start fails after an earlier one succeeded, carrying
  `successfullyStartedJobs`, `failedDocumentType`, and the underlying
  `SuperDocsRequestError`. It performs no approval, denial, cancellation,
  retry, or compensation — it only stops the job ids from being lost.
- The live driver counts accepted chat starts as they occur and reports them
  as `locallyObservedSuccessfulChatStarts`, explicitly not as billing truth.

The next live run is a single controlled experiment
(`runSessionLockExperiment`, opt-in and not wired into the app or the UI) that
answers one question: **can SuperDocs start a second pinned `chat/async` job
in the same session while the first job is `awaiting_approval`?** Sequence:
start the Terms pinned job → poll it to `awaiting_approval` → run its
targeting/structural/coverage gate → **do not approve it** → only then attempt
the Returns pinned start. If the Terms gate fails, Terms is denied and Returns
is never started, so that case costs one chat start rather than two.

If that instrumented second start returns 409 while Terms is
`awaiting_approval` — with a captured status, provider code, detail, and
request id — we will have enough evidence to document the finding in
`SUPERDOCS_ISSUES.md` as:

    Observed provider behavior → PolicySet risk → mitigation/workaround
    → remaining limitation

Issue 3 is deliberately **not** written yet: one observation with a discarded
response body is weaker evidence than Issues 1 and 2 rest on, and adding it
now would undercut them. Issues 1 and 2 are unchanged.

### Phase 5 session-lock experiment — run once, question still unanswered

Ran the controlled experiment live (1 paid chat start; the second was never
issued). It did **not** answer the session-lock question, because the Terms
job failed its own coverage gate before the second start could be attempted —
which is exactly the guard the experiment was specified with.

- Terms pinned job `c3abf5ad…` reached `awaiting_approval` with **one**
  proposal, then failed the managed-occurrence coverage gate: the proposal
  updated the body prose (both the "within 30 days of delivery" and
  "30-day window" occurrences) but left the **"Return window (days): 30"
  summary fact line untouched**.
- The gate denied every pending change. Verified afterwards by read-only GETs:
  the job settled to `completed` with 0 pending changes, and the authoritative
  Terms document still reads 30. Returns, Privacy, and Warranty are unchanged.
  Canonical `PolicyProfile.returns.windowDays` never left 30.
- `locallyObservedSuccessfulChatStarts: 1` (locally observed, not
  provider-confirmed). The Returns start was never attempted, so **no evidence
  about concurrent pinned jobs was gathered**: no second 409, no new provider
  diagnostics. The session-lock classification stays
  UNDOCUMENTED_SUPERDOCS_LIMITATION / moderate confidence, unchanged, and
  remains **unresolved and undocumented in `SUPERDOCS_ISSUES.md`**.
- Evidence: `tmp/phase5-session-lock-report.json` and the sanitized proposal
  snapshot under `tmp/policyset-proposal-evidence/`.

**This materially strengthens Issue 1.** The incomplete managed-fact update was
previously observed only on unpinned, multi-document jobs, which left open the
possibility that message-based routing was the cause. This run reproduces the
same partial update on a **single-document `document_id`-pinned job** whose
instruction explicitly named both the fact line and the body prose and said
"Leave no 30-day return window anywhere in Terms of Service". The model also
reported `"✅ I have updated the return window from 30 days to 14 days in the
Terms of Service document."` while one managed occurrence was still stale — a
confident completion claim that does not match the batch it produced. Pinning
therefore removes cross-document routing loss but does **not** remove
within-document incompleteness.

**The AI completion claim is not trusted as a correctness signal.** The
correctness signals are proposal coverage before approval, and validation of
the final authoritative document afterward — never the provider's narrative
text about what it believes it did.

This finding is now written up, sanitized, as **Issue 3** in
`SUPERDOCS_ISSUES.md` ("Pinned single-document edit can report completion while
leaving an explicitly named managed occurrence unchanged",
`SUPERDOCS_ROUGH_EDGE` / possible bug, moderate-to-high confidence in the
observed behavior). Issue 3 covers only this coverage/completion-claim finding
— it is **not** about session locking. Issues 1 and 2 are unchanged.

To actually answer the session-lock question, a rerun needs the Terms batch to
pass its gate first. That is not a retry of the same experiment — it depends on
a non-deterministic provider behavior, so it should be treated as a fresh run
with its own budget.

### Template cleanup — reduce duplicated managed facts (implemented)

**Observed.** Generated documents carried the same canonical fact twice: a
machine-style summary line (e.g. `Return window (days): 30`) in a
`<dl class="canonical-facts">` block, plus natural legal prose stating the
same value. Every duplicated representation was another place that had to
stay synchronized, and another chance for a partial AI edit to leave the
document self-contradictory — this is exactly the shape of the rough edge
recorded as Issue 3 in `SUPERDOCS_ISSUES.md`. The duplication was largely
self-inflicted: PolicySet already holds the canonical value in
`PolicyProfile` and surfaces it in the Policy Facts panel, and every field the
summary block listed was already present, individually wrapped in
`data-managed-field`, inline in the document's own prose.

**Mitigation implemented.** Canonical structured values remain in
`PolicyProfile` / the Policy Facts UI. `renderers.ts` no longer emits the
`canonical-facts` summary block in any of the four documents — generated
policies contain only natural legal prose (plus contact details, effective
dates, governing law, and the attorney-review disclaimer). For
`returns.windowDays` specifically, Terms and Returns still each express the
managed value twice in prose ("within N days of delivery" and "the same
N-day window"); the managed-occurrence model
(`src/domain/managed-occurrences.ts`) was updated to drop the retired
`fact_label` occurrence kind and its pattern, so the coverage model for both
documents is now `["policy_prose"]`, covering only the occurrences that still
exist. The SuperDocs edit instruction (`buildTargetedSynchronizedInstruction`
in `src/superdocs/policyset.ts`) was updated to stop naming the removed
summary line.

**Remaining limitation.** This does not remove the need for deterministic
coverage validation. Legal prose still states the same fact more than once in
the same paragraph, so multi-occurrence coverage checking
(`assertSynchronizedProposalCoverage`) remains required and unchanged in
strength — it still fails closed on any missing or incomplete occurrence
before approving a batch.

### Transient initialization failures

Transient `SuperDocs is unavailable` failures during session
initialization/upload have now occurred in two independent validation sessions
(once in Phase 4, twice in the targeted-job run). They are transport-level
failures with no HTTP response at all, they occur before any paid chat
operation, and live validation retried them safely. Production currently
surfaces them rather than retrying automatically — only the git-ignored live
driver retries. This is **not** classified as a SuperDocs bug: a transport
failure with no response body cannot be attributed to the provider rather than
the network path, and there is no reproduction. It is not recorded in
`SUPERDOCS_ISSUES.md`.

## Checks run

- `npm test` — 61 passed
- `npm run typecheck` — passed
- `npm run lint` — passed
- `npm run build` — passed (Next.js 16.3.0)

## Known limitations

- Profile and changesets are in-memory functions only; there is no database or session store
- Phase 5 intentionally exposes only `returns.windowDays`; other managed facts
  remain read-only, and the new coverage gate is likewise scoped to
  `returns.windowDays` only
- The SuperDocs adapter does not implement continue prompts, session-job recovery, retries, or `open_mode=new_focused`
- Validator covers PolicySet-managed facts, not legal compliance
- No Phase 5 live run has reached an approved synchronized commit. All three
  runs used the now-retired unpinned single-job strategy and correctly failed
  closed for the reasons in `SUPERDOCS_ISSUES.md`; `returns.windowDays` has
  never left 30 in a live run. The explicit-targeted-job fallback was run live
  once and failed at job start (probable session-level job-in-flight
  restriction, see above); it has not yet produced a reviewable batch.
- The instrumented session-lock experiment was attempted once: the Terms
  pinned job started and reached `awaiting_approval`, but it failed the
  managed-occurrence coverage gate before the guarded second (Returns) start
  could be attempted, so the experiment never issued that second call. No new
  409 evidence was collected. Whether two pinned jobs can coexist in one
  session therefore remains unknown, and no mitigation (sequenced starts vs. a
  session per affected document) has been chosen or implemented.
- Intake/workspace state is not persisted across refresh
