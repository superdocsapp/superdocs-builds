# Track-Changes Triage — a Word add-in built on SuperDocs

Built for SuperDocs' Round-2 engineer task, assigned card "Word add-in:
track-changes triage" (difficulty band S2).

**What it does:** open a Word document that came back full of tracked
changes from several reviewers. The pane groups every change by reviewer
and lets you act on them by plain-English instruction — "accept all of the
proofreader's typo fixes," "reject the deletions in the payment section" —
previewing exactly what will happen before anything touches the document.
It also lists reviewer comments, drafts a reply with one click, and lets
you resolve the thread. Every classification and instruction match is
powered by a real call to the SuperDocs `/v1/chat` API.

**Who it's for:** an editor, legal reviewer, or supervisor triaging a
marked-up return, per the assigned card.

## Architecture — why the document mutation never touches SuperDocs

The brief's own honesty note on this card says multi-reviewer attribution
across a full file round-trip isn't something SuperDocs promises today.
Rather than build on that and hope, this add-in sidesteps it entirely:

- **Reading and mutating tracked changes and comments** happens exclusively
  through Word's native Office.js API (`Word.TrackedChange`,
  `Word.Comment` — see `word-changes.js`). Accepting or rejecting a change
  is a direct `trackedChange.accept()`/`.reject()` call on Word's own
  document model. Nothing is ever exported out of Word and re-imported.
  That is *why* reviewer names/timestamps survive and every other
  reviewer's marks stay untouched — not because SuperDocs' pipeline
  promises it, but because SuperDocs' pipeline is never in that path.
- **SuperDocs' `/v1/chat`** (see `superdocs-client.js`) does the one thing
  it's actually needed for: reasoning over text. It classifies each change
  as substantive/stylistic/typo, and turns a free-text instruction into a
  concrete list of `{change_id, accept|reject}` decisions for the pane to
  preview. No `document_html`, no `approval_mode` is ever sent — these are
  plain analysis calls, confirmed live against the real API (not just the
  docs) to be free (`was_billable: false, ops_charged: 0`), which is what
  "budget your operations" should look like for a feature that doesn't
  need document mutation at all.

```
 Word document (tracked changes + comments)
        │  Office.js: getTrackedChanges(), getComments()
        ▼
 word-changes.js  ──── digest of changes/comments ────▶  superdocs-client.js
        │                                                        │
        │                                          POST /v1/chat (classify /
        │                                          interpret / draft reply)
        │◀─── {change_id, action, reason}[] ─────────────────────┘
        ▼
 preview batch (taskpane.js) — human approves/edits the batch
        ▼
 word-changes.js: trackedChange.accept()/.reject(), comment.reply()/.resolved
```

## Setup

No Node, no npm, no build step — same reasoning as the rest of this round's
"stranger can run it in minutes" scoring: plain HTML/CSS/JS, React loaded as
a UMD bundle from a CDN with `htm` standing in for JSX.

1. **Get a SuperDocs API key.** Sign in at `use.superdocs.app` → gear icon
   → Settings → API Keys → Create API Key (starts with `sk_`). Or use the
   agent self-signup flow in the docs if you're scripting this.
2. **Serve this folder over HTTPS** (Word refuses plain HTTP, even on
   localhost):
   ```bash
   python serve.py
   ```
   This generates a one-off self-signed cert with `openssl` (ships with Git
   for Windows / any Mac or Linux shell — no Node needed) and serves on
   `https://localhost:3001`. Verified working: `taskpane.html`,
   `manifest.xml`, and the JS/asset files all return `200` over the
   generated cert.
3. **Sideload the add-in in Word (desktop):** Insert tab → Add-ins → My
   Add-ins → Upload My Add-in → select `manifest.xml` from this folder.
   Word and your browser will warn about the self-signed cert the first
   time — expected for local dev, click through it.
4. **Open a document with tracked changes and comments**, open the
   "Triage Changes" pane (Home tab, or via the sideload prompt), paste your
   `sk_...` key into the settings panel (stored only in that browser
   profile's `localStorage`, never anywhere else), then **Load tracked
   changes**.

`REACT_APP_*`-style env vars aren't used here on purpose — there's no build
step to inject them into, so the API key is entered once in the running
pane instead. If you're scripting a headless demo, `SuperDocsClient.setApiKey("sk_...")` in the browser console does the same thing `config.js` would.

## SuperDocs features used

- `POST /v1/chat` (plain, non-mutating) — classification and instruction
  interpretation. This is the whole SuperDocs integration; see
  "Architecture" above for why upload/approve/export aren't part of the
  core feature.

## What broke (bug report — also filed via the in-app bug button / task email)

**`POST /v1/chat/{session_id}/approve` requires a `job_id` that the
synchronous `/v1/chat` endpoint's `approval_mode: "ask_every_time"` never
returns.** Reproduced live:

1. `POST /v1/chat` with `approval_mode: "ask_every_time"` on an edit
   instruction returns `document_changes.pending_changes[].change_id` (a
   real, well-formed UUID) — no `job_id` anywhere in the response.
2. `POST /v1/chat/{session_id}/approve` with `{"change_id": "<that uuid>", "approved": true}` → `422 Field required: job_id`.
3. Trying `{"job_id": "<that same uuid>", ...}` → `404 Job not found`.
4. The only way to get a `job_id` that `approve` actually accepts is
   `POST /v1/chat/async`, then polling `GET /v1/jobs/{job_id}` until
   `status: "awaiting_approval"`, then approving with *that* job's id —
   confirmed working end to end.

So the sync endpoint's own HITL fields are currently unactionable through
the documented approve flow; only the async job path works. This add-in
doesn't depend on either path (see Architecture), but anyone building HITL
document editing on the sync endpoint would hit this immediately.

**Secondary, minor:** a plain analysis-only `/v1/chat` call with an
instruction like "classify these, don't modify the document" occasionally
returns a generic non-answer ("I found what I needed, but I wasn't able to
put together a safe reply...") rather than the requested analysis. Adding
an explicit "respond with ONLY a JSON array" instruction and a concrete
schema example reliably fixed it in testing — worth noting in the prompting
guidance in the docs, since the natural first attempt at a read-only
question doesn't work well.

## What I cut, and why

- **No manual multi-select batch.** The only way to build a batch is
  through the instruction bar (SuperDocs interprets it) — there's no
  checkbox-per-change manual selection UI. The assigned card is explicitly
  about acting "by instruction," so this keeps the surface area focused;
  a manual mode would be a natural next addition.
- **"Section" filtering is a heuristic, not a guarantee.** A change's
  "section" is the nearest preceding Heading-styled paragraph, detected by
  walking the document body once. It's genuinely useful for instructions
  like "the deletions in section 2," but a document with no heading styles,
  or headings that repeat text, will produce a best-effort (occasionally
  wrong) section label. Classification and instruction-matching don't
  depend on section being right — it's additional context, not load-bearing.
- **Replace-pair merging is adjacency-based.** A reviewer's "replace X with
  Y" shows up in Word's model as a Deletion immediately followed by an
  Insertion from the same author; this add-in merges exactly that adjacent
  pattern into one triage-able item. A replace edit interleaved with a
  different reviewer's edit in between would not be merged (shown as two
  separate items instead) — correct, just less tidy.
- **Not tested inside real Word.** I don't have a Word desktop/Word Online
  session in the environment I built this in. Every Office.js call is
  written directly against Microsoft's documented `Word.TrackedChange` /
  `Word.Comment` API (properties, methods, and required API-set versions
  confirmed against the live Microsoft Learn reference, not memory), and
  every SuperDocs call in `superdocs-client.js` was exercised against the
  real, live API with a real key before being wired into the UI — but the
  Word-side integration itself is the one part of this build I could not
  personally click through. That's a real limitation, not a hidden one.

## Demo

See the round's submission video (Task 4) for a walkthrough — [link added
via the submission form].

---

Built for the SuperDocs task by Priti More.
