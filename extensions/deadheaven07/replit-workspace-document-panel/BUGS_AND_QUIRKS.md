# SuperDocs API - Bugs, Quirks & Integration Notes

Real-world technical hurdles discovered while building the **Replit Workspace Document Panel** extension. Each entry follows the same structure:

- **Symptom** - what you observe
- **Exact Reproduction Steps** - how to trigger it
- **Expected vs. Actual Behavior** - what should happen vs. what the API/engine does
- **Implemented Workaround** - what the extension actually does about it

---

## 1. Double-JSON Encoding in `pending_changes`

**Symptom:** `jobStatus.metadata.pending_changes` is a string containing a JSON-encoded object whose `content` field is *itself* a JSON-encoded string. A single `JSON.parse()` yields a string, not an object, and `metadata.pending_changes.changes` is `undefined` at runtime (TypeScript happily compiles because `metadata` is `Record<string, unknown>`).

**Exact Reproduction Steps:**
1. Call `chatAsync` with `approval_mode: 'ask_every_time'`.
2. Poll `/v1/jobs/{job_id}` until `status === 'awaiting_approval'`.
3. Read `jobStatus.metadata.pending_changes`.
4. Attempt `JSON.parse(pending_changes).changes`.

**Expected vs. Actual Behavior:**
- Expected: `pending_changes` is a plain JSON object with a `changes` array.
- Actual: `pending_changes` is a string like `"{\"batch_id\":\"...\",\"content\":\"{\\\"changes\\\":[...]}\"}"` - the payload is encoded twice.

**Implemented Workaround:** `src/utils/parser.ts` (`parseProposedChangeBatch`) performs a two-pass decode: parse the outer JSON, then parse `outer.content` if it is a string (or use it directly if the API one day returns an already-parsed object). Both string and object inner content are handled, and every field is coerced defensively (`String(...)`, `Number(...)`) because the inner shape is untyped.

---

## 2. Large Context Payload Latency Spikes

**Symptom:** Generation jobs take 60s+ (or time out) when selected files exceed a few hundred KB; polling runs for the full 10-minute `MAX_POLLS` window with no result.

**Exact Reproduction Steps:**
1. Select a large file set (e.g., a `node_modules`-lite repo with several 100KB+ source files).
2. Generate a document with the full project context in the instruction.
3. Watch `pollJob` latencies climb from 1-5s to 10s+.

**Expected vs. Actual Behavior:**
- Expected: generation time scales gracefully with project size.
- Actual: instruction size is proportional to total context; large instructions measurably increase per-poll latency and total job time, and can push past the job timeout.

**Implemented Workaround:** `buildProjectContext` in `src/services/replit.ts` enforces a **500KB total context cap**. Files that would exceed the limit are skipped and listed in a warning block prepended to the instruction (`[WARNING: N file(s) skipped due to context size limit...]`) so the model knows coverage is partial. Regeneration (see entry 5) further reduces payloads by sending **only changed files** instead of the full project.

---

## 3. AbortController Threading Edge Cases

**Symptom:** Cancelling one operation can (a) leave the retry backoff timer running, (b) fail to abort the in-flight `fetch`, or (c) let a *previous* operation's completion callback clobber state set by a newer operation.

**Exact Reproduction Steps:**
1. Start a generation, then click **Cancel** while `waitForJob` is sleeping between polls.
2. Start generation A, immediately cancel, then start generation B.
3. Start generation during a transient network failure (retry backoff active), then cancel.

**Expected vs. Actual Behavior:**
- Expected: cancel aborts everything synchronously and no stale callbacks fire.
- Actual: `setTimeout`/`setInterval` sleeps are not cancelled by `AbortSignal` alone; a shared module-level `abortControllerRef` means an older operation's response can overwrite the newer operation's state if the old signal wasn't checked at every await boundary.

**Implemented Workaround:**
- `withRetry` and `waitForJob` register an `abort` listener that clears the sleep timer and rejects with a named `AbortError`.
- The hook checks `signal.aborted` **after every single await** (`upload`, `chatAsync`, `waitForJob`, poll progress) before mutating state.
- `AbortError` is caught and suppressed at the top of every action - it never surfaces as a user-facing failure.
- Each action creates its own `AbortController` and stores it in `abortControllerRef`; `cancel()` aborts the current one.

---

## 4. Dual-Layer State Merge Race (localStorage vs `.superdocs-state.json`)

**Symptom:** After a browser refresh, the panel restores an *older* session (wrong `sessionId`/`documentId`), or loses file-selection state even though the workspace state file exists.

**Exact Reproduction Steps:**
1. Generate a document (state saved to both layers).
2. Open a second tab on the same Repl; generate again (both layers update).
3. Close the second tab, refresh the first.
4. Alternatively: clear browser data (localStorage gone) but keep the workspace file.

**Expected vs. Actual Behavior:**
- Expected: the newest state always wins.
- Actual: the two stores are written by different code paths (synchronous `localStorage` vs async workspace `writeFile`), so `lastUpdated` timestamps can disagree by milliseconds; with one layer missing, either layer could be stale. Corrupt/partial JSON in one layer previously crashed the whole load.

**Implemented Workaround:**
- `mergePersistedStates` (pure function in `src/hooks/useStatePersistence.ts`) picks the layer with the **higher `lastUpdated`** when both exist, falls back to whichever layer exists, and otherwise returns the default empty state.
- Both loaders wrap `JSON.parse` in try/catch and validate with `isValidState`; corrupt payloads degrade to `null` instead of throwing.
- Covered by `tests/persistence.test.ts` simulating browser refresh, container re-entry (localStorage lost), browser data cleared, and corrupt-payload scenarios.

---

## 5. Regeneration Must Be a Review Loop, Not a Full Rebuild

**Symptom:** "Regenerate" re-sends the *entire* project context with the full generated prompt; SuperDocs then proposes edits across the whole document, touching sections whose source never changed, and revision prompts grow exponentially across iterations.

**Exact Reproduction Steps:**
1. Generate a README, approve all changes.
2. Edit one source file.
3. Click "Regenerate Document".
4. Inspect the new `ProposedChangeBatch`: changes appear in sections unrelated to the edited file, and the instruction embeds the previous generated prompt.

**Expected vs. Actual Behavior:**
- Expected: only drifted sections are re-proposed; previously approved sections are untouched.
- Actual: full-context regeneration re-reviews everything and accumulates prior revision text inside the next instruction (instruction bloat).

**Implemented Workaround:** `src/services/revision.ts` implements a **hash-diff review loop**:
1. `computeSourceDiff` compares persisted baseline hashes (`.superdocs-state.json` → `fileHashes`) against current file contents and returns only `changed`/`added`/`removed` files (paths sorted for determinism).
2. `buildRevisionMessage` sends the **stable original user instruction** + a list of changed files + the **full current content of changed files only**. Unchanged files are never serialized, so the model cannot propose edits on them.
3. `planRegeneration` short-circuits when hashes are identical: **no chat job is created**, the proposed-changes array is provably empty (zero drift), and approved sections are preserved by construction.
4. When drift exists, the message goes through `chatAsync` with `approval_mode: 'ask_every_time'`, returning granular `ProposedChange` ops (insert/replace/delete) straight into the Review tab.
5. Baseline hashes are updated only after a successful export, so the next diff is measured against the last *delivered* state.

---

## 6. `approval_mode` Default Is `'never'` (Silent No-Review)

**Symptom:** A `chatAsync` call returns `status: 'completed'` with no `ProposedChangeBatch`, bypassing the human-in-the-loop review entirely - even though the code "always" passes `ask_every_time`.

**Exact Reproduction Steps:**
1. Call `POST /v1/chat/async` with `{ message, session_id }` only.
2. Poll the job.

**Expected vs. Actual Behavior:**
- Expected: some default that matches the documented review workflow (or a validation error).
- Actual: omitting `approval_mode` defaults to `never` - the document is modified with zero user visibility.

**Implemented Workaround:** Every `chatAsync` call in `useSuperDocs.ts` (`generateDocument`, `regenerateFromSource`) explicitly passes `approval_mode: 'ask_every_time'`; the Review tab is the only path forward to export. Documented in `README.md` under core capabilities.

---

## 7. `approveChanges` Requires Full Change Objects, Not IDs

**Symptom:** Sending `{ approved: true, changes: ['change_id_1'] }` (or a stripped subset) results in a 4xx validation error, or silently applies only some changes.

**Exact Reproduction Steps:**
1. Receive a batch of proposed changes.
2. Approve with only the `change_id` values in the `changes` array.

**Expected vs. Actual Behavior:**
- Expected: IDs would be sufficient for an approval API.
- Actual: the API validates the full `ProposedChange` object structure (`operation`, `chunk_id`, `old_html`/`new_html`, `ai_explanation`, `insert_after_chunk_id`, `document_id`).

**Implemented Workaround:** `ReviewTab` passes the exact parsed objects from the batch to `approveChanges` (no reconstruction); `tests/superdocs.test.ts` locks in the full-object payload shape.

---

## 8. Session Continuity Is Mandatory Across Operations

**Symptom:** Regeneration or edits produce documents with no memory of prior conversation; approvals 404 with "session not found".

**Exact Reproduction Steps:**
1. Generate a document (session A).
2. Call `chatAsync` without reusing `session_id` (or with a fresh `initSession`).
3. Call `/v1/chat/{session_id}/approve` with a session the job was not created on.

**Expected vs. Actual Behavior:**
- Expected: sessions are optional/auto-created.
- Actual: a new session loses document history and context; `approveChanges`/`continueJob` require the *original* session in the URL path.

**Implemented Workaround:** The `session_id` from `uploadDocument` is threaded through every subsequent call and persisted to both state layers (`sessionId` in `.superdocs-state.json` + localStorage), so refreshes and container re-entries restore the same session.

---

## 9. Retrying Mutations Creates Duplicate Side Effects

**Symptom:** After a transient network error, a naive `fetch` retry wrapper produces duplicate documents/jobs/exports (multiple uploads of the same file, doubled export artifacts).

**Exact Reproduction Steps:**
1. Wrap `uploadDocument`/`exportDocument` in a blanket retry-on-network-error helper.
2. Induce a network failure at the exact moment of the POST.
3. Retry.

**Expected vs. Actual Behavior:**
- Expected: idempotent behavior under retry.
- Actual: `uploadDocument`, `chatAsync`, `approveChanges`, `continueJob`, and `exportDocument` are non-idempotent - each retry creates a new document, job, approval, or export.

**Implemented Workaround:** The client (`src/services/superdocs.ts`) only auto-retries safe/read operations (`initSession`, `pollJob`, `waitForJob`) with exponential backoff (1s → 2s → 4s, max 3). Mutations are never retried; failures surface in the error banner with explicit Retry/Dismiss user actions. Enforced by `tests/revision.test.ts` (retry suite).

---

## Quick Reference: REST Endpoints

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Init Session | `/v1/sessions/init` | POST |
| Upload Document | `/v1/documents/upload-base64` | POST |
| Chat/Edit | `/v1/chat/async` | POST |
| Poll Job | `/v1/jobs/{jobId}` | GET |
| Approve Changes | `/v1/chat/{sessionId}/approve` | POST |
| Continue Job | `/v1/chat/{sessionId}/continue` | POST |
| Export Document | `/v1/documents/export` | POST |
| Download Export | `{download_url}` | GET |

*Last updated: 2026 - Based on SuperDocs API integration for Replit Workspace Document Panel*