# Reference Letter Drafter

Built on [SuperDocs](https://superdocs.app) for the SuperDocs engineering task (Task 2, assigned build:
reference and recommendation letter drafter).

A manager or academic fills in a structured intake. The app drafts a letter in SuperDocs, checks that
the result reads as strongly as the writer actually meant it, and hands both the proposed changes and
the calibration findings to the writer to approve or reject, change by change, before anything is
written.

**The one thing this is built to do:** a lukewarm reference reads as lukewarm.

---

## Run it

```bash
git clone <this repo> && cd reference-letter-drafter
cp .env.local.example .env.local     # add SUPERDOCS_API_KEY
npm install
npm run dev                          # http://localhost:3000
```

That is the whole setup. No database, no migrations, no Docker, no queue.

```bash
npm test           # 116 tests, no key, no calls to SuperDocs, no cost
npm run typecheck
npm run verify     # both
```

The tests run on a fresh clone with an empty `.env.local`. If a test needs a key, it is testing the
wrong thing.

---

## The problem, and why the obvious version does not work

Everyone building this feature builds the same thing: a form, a prompt that says "write a reference
letter, tone: lukewarm", and whatever comes back.

It does not work. Language models are trained on published, positive reference letters, and they pull
warm. Told a candidate is mediocre, a model still produces "a capable and dedicated professional whom
I am pleased to recommend." The writer skims it, it sounds like a letter, they send it. The reference
they meant to give and the reference they gave are different documents, and the only person who finds
out is the candidate, later, in a way nobody traces back.

So the interesting part is not generation. It is **verification**: proving the letter carries the
weight the writer chose, and telling them when it does not.

## How this app handles it

### 1. The writer declares the band. The model does not infer it.

Four bands (`reluctant`, `mixed`, `solid`, `strong`), picked explicitly in the form. Each has a
contract, a banned vocabulary, and, for the lower two, an expectation that some qualifier appears
somewhere.

Two rules the form enforces that most versions of this do not:

- **A claim with no evidence behind it is rejected at validation.** You cannot type "brilliant
  engineer" and leave the supporting box empty. The letter may only assert what you supplied.
- **A `mixed` or `reluctant` letter with no reservations stated is rejected.** That combination is
  someone clicking through a form, and it cannot produce a letter that reads as measured.

### 2. Two calibration checks, layered, neither of which is the drafter

**Deterministic** (`lib/calibration/deterministicAudit.ts`). No model call, no key, no network, about
a millisecond, same answer every time. Banned phrases per band with context guards, so "outstanding
balance" does not fire but "an outstanding candidate" does. Plus two checks a phrase list misses:

- **No qualifier anywhere.** A `mixed` letter containing no hedge, caveat or limitation has been
  quietly rewritten into a warm letter. This is the most common silent inflation, and no banned-word
  list catches it, because nothing bad was said. Something honest was omitted.
- **Dropped reservations.** Reservations the writer typed are matched into the letter by content
  words, not exact strings, so rephrasing passes and omission fails.

**SuperDocs verifier** (`lib/calibration/verifier.ts`). A second, isolated SuperDocs chat call — fresh
session, no cross-session memory, told explicitly not to edit its scratch document — reads the finished
letter and infers what band a reader would take from it. It gets the letter and the supplied facts, and
nothing else: not the declared band, not the drafting prompt, not the intake. A verifier that knows the
intended answer will agree with it, and its agreement means nothing.

This is the only AI call in the app besides the draft itself, and it goes through the same SuperDocs API
as everything else — no other model provider is involved, and it needs no separate key. Confirmed against
the live API, a pure Q&A turn like this (told not to touch the document) is not billed as an operation.

Deliberate hard-coded defenses alongside intelligent logic, not instead of it. The lexicon catches the
blatant cases for free on every draft; the verifier catches the subtle ones.

### 3. Findings are surfaced, never auto-fixed

Nothing in the audit rewrites the letter. Every check produces a finding a human acts on. The writer
signs it, and a tool that silently corrects someone's assessment of a colleague has substituted its
judgement for theirs.

### 4. A skipped check is never rendered as a pass

If no verifier is configured, the report says `verifier: "unavailable"` with the reason, and the UI
says "no findings from the checks that ran" rather than "looks good." `no findings` and `no checks`
are different answers and the app never conflates them.

---

## At the review page

Three things added after the initial build, all at the review screen:

**Full letter view** (`components/LetterPreview.tsx`). The diff cards show what changed as text; this
renders the actual HTML, through DOMPurify, so formatting-only changes (paragraph spacing, emphasis) are
visible at all — a text diff can't show a `margin-bottom` that was added to a `<p>` tag, and a real one
of those changes looking identical in a text-only view is exactly what prompted this. See "No
`dangerouslySetInnerHTML` almost anywhere," below, for why this is the one exception. Before the current
batch is approved it is labelled a preview, built from the batch's `new_html`, because it has not been
written yet; once the job is `completed` it reads the actual committed document.

**Ask for a change** (`components/ReviseBox.tsx`, `POST /api/revise`). A freeform message box for
requests the structured intake has no field for — "make the second paragraph shorter." It sends another
`chat/async` turn on the same session, same `ask_every_time` gate, so the result lands as ordinary diff
cards on the same page rather than being applied directly. Disabled while a batch is still undecided, so
a new request cannot land on top of one nobody has answered yet.

**Past letters** (`lib/history.ts`, `components/HistoryList.tsx`). A local list — `localStorage`, not a
database — of session id, job id, subject name, writer name, band and dates, written whenever a draft
starts, a revision is sent, or a job completes. It does NOT store the intake content: no evidence, no
reservations, no tone notes. Those still live only in `sessionStorage` and are gone on tab close, per the
original privacy call (see "Engineering decisions," below) — this list is a pointer back to a SuperDocs
session, not a copy of what was typed. From the list you can re-export a finished letter, or resume
review of one still in progress; resuming reconstructs a minimal `Intake` from what history actually
kept, so a resumed calibration audit has less to check against (no evidence, no reservations) than the
original session had. That tradeoff is the reason this list is opt-in in spirit: nothing here claims to
be the intake you originally typed.

---

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the diagram and the failure paths.

```
Intake form --> /api/session   --> SuperDocs: upload starter document
            --> /api/draft     --> SuperDocs: chat_async, approval_mode=ask_every_time
                                   (idempotent: a double-click cannot buy two operations)
            <-- /api/jobs/[id] <-- SuperDocs: job status
                                   (pending changes parsed here, on the server, once)
            --> /api/audit         calibration: lexicon + injection scan + verifier
            --> /api/approve   --> SuperDocs: per-change approve / reject
            --> /api/export    --> SuperDocs: .docx
```

The letter lives in SuperDocs the entire time. This app never holds it as its own source of truth,
never stores it, and never renders it as HTML. It is intake, calibration and orchestration on top of
SuperDocs, not a version of SuperDocs.

### SuperDocs surfaces used

| Surface | Where |
| --- | --- |
| Upload | `POST /documents/upload`, starter document per session |
| Chat (async) | `POST /chat/async` with `approval_mode: "ask_every_time"` |
| Chat (verifier) | Second `POST /chat/async` call, fresh session, `approval_mode: "approve_all"`, told not to edit its scratch document — the second-reader calibration check |
| Chat (revise) | Another `POST /chat/async` call, same session, same `ask_every_time` gate — the "ask for a change" box at the review page |
| Approve | `POST /chat/{session}/approve`, item by item |
| Export | `POST /documents/export`, `.docx` |
| Continue | `POST /chat/{session}/continue` for large-edit prompts |
| Templates | `GET/POST /templates` — a prior letter carries the writer's voice |
| Cross-session memory | `cross_session_memory_key` scoped to the writer's email |
| Usage | `GET /agents/whoami`, shown before you spend |

---

## Engineering decisions worth defending

**No database.** State is three strings in `sessionStorage` plus SuperDocs session ids. A database
here buys nothing and costs the clone-to-running-in-minutes property. `sessionStorage` rather than
`localStorage` on purpose: the intake contains a third party's performance history and should not
outlive the browser tab.

**No `dangerouslySetInnerHTML` almost anywhere.** The first version rendered proposed-change HTML behind
a sanitizer that silently no-opped during SSR. That HTML comes from a model that has just read intake
text a third party may have written. Rather than fix the sanitizer, the per-change diff cards render a
word-level LCS diff over extracted text instead (`lib/diff.ts`) — that XSS class is gone rather than
filtered there, and the diff reads better than a before/after pair for judging a content edit.

`dompurify` came back for exactly one view: the full letter preview (`components/LetterPreview.tsx`,
`lib/sanitizeHtml.ts`), added after a text-only view made a real formatting change (added paragraph
spacing) look like nothing had happened at all — confirmed by diffing the exported `.docx` XML before
and after, which showed the change had genuinely landed even though the app's text view couldn't show
it. `style` is on the sanitizer's allowlist so spacing survives; DOMPurify still strips dangerous CSS out
of whatever the attribute contains, so allowing it is not the same as trusting its contents. This is the
one `dangerouslySetInnerHTML` in the repository, scoped to a view that exists to show formatting, not to
judge content — the diff cards, where the actual approve/reject decisions happen, are still text-only.

**The double-parse is handled on the server, once.** SuperDocs delivers proposed changes as a
JSON-encoded string. `lib/parsePendingChanges.ts` accepts a plain array, a JSON string, a
double-encoded string, a nested key, or per-item encoded strings. A change missing an id or missing
content is **refused**, not defaulted — an approve button over a blank diff is worse than an error,
because a reviewer will click it.

**Retry only what is safe to retry.** `lib/http.ts` retries 429 and 5xx with full-jitter backoff and
never retries 4xx. `startDraftJob` sets `retries: 0`: retrying a request that may already have been
accepted upstream bills you twice for one letter. Exports retry freely, because exports do not cost
operations.

**Errors name the cause and the fix.** A 401 returns "the API key was rejected, check
SUPERDOCS_API_KEY in .env.local", not "SuperDocs returned 401". The upstream body never reaches the
client, since it can echo back the request and with it anything the writer typed.

**Idempotency where operations cost money.** `/api/draft` keys on a hash of session plus instruction,
collapses concurrent duplicates by awaiting the original promise rather than racing it, and does not
cache failures so a retry after a fix still works.

**Configuration over code.** Bands, banned phrases, hedges and injection patterns are data in
`lib/calibration/lexicon.ts` and `lib/injection.ts`. A new band, a new phrase, or a UK-vs-US
vocabulary split is an edit to a data structure. The same file feeds both the drafting prompt and the
auditor, so the system cannot grade itself against rules it never sent.

**Prompt injection is reported, not stripped.** Intake text is fenced with a token that cannot be
forged from inside the value, and the rules are stated before the untrusted content rather than after.
Detection surfaces a finding naming the field. It is not deleted: silently editing what someone typed
is its own failure, and the realistic case is a manager pasting in a candidate's self-written brag
sheet, which they should know about.

---

## What I cut, and why

- **No auth.** Single-user local app. Deploying this for real users needs auth in front of
  `/api/draft` before anything else, since it spends money per call. Stated rather than pretended.
- **No structured revision loop from findings.** `buildRevisionInstruction` exists and is tested but is
  not wired to a button that turns a specific finding into a revision automatically. Rejecting a change
  with feedback already lets SuperDocs revise on the next pass, and the freeform "ask for a change" box
  (below) covers the general case; a third, narrower path would have been a shallower version of
  something that already works twice over.
- **No streaming (SSE).** Polling with backoff is enough for a job that returns in seconds to minutes,
  and it survives a dropped connection without reconnect logic.
- **No document management system.** Letter history (below) is a local list of session ids and two
  names, not a store of letter content. A real archive with search, sharing and retention policy is out
  of scope for the same reason it was originally cut: it is a different product.

---

## Where this breaks

Written before you find it yourself.

- **Idempotency is process-local.** One Next.js instance, one in-memory map. Behind two instances or
  after a restart, a duplicate draft can still get through. The fix is a shared store keyed
  identically; nothing else about the design changes.
- **The verifier is a language model, not an instrument.** Blinding it to the declared band removes
  the obvious bias. It does not make it neutral, and its own tendencies are unmeasured here.
- **The lexicon is English, in a workplace and academic register.** It will underfire on other
  registers and will not transfer to other languages without a new phrase set.
- **Dropped-reservation matching is a bag-of-words heuristic.** A letter that reuses a reservation's
  vocabulary while inverting its meaning ("far from struggling with deadlines") passes the check. The
  verifier is the backstop and is not guaranteed to catch it either.
- **The band scale is ordinal and drift arithmetic treats it as interval.** The gap between `mixed`
  and `solid` is probably not the same size as between `solid` and `strong`. Mean drift is a
  directional signal, not a measurement.
- **No test covers the real SuperDocs API.** Every test runs against a local HTTP server or pure
  functions. The wire contract is exercised only by running the app and the eval, so a breaking
  upstream change would not be caught by `npm test`.
- **The full letter preview trusts DOMPurify, not a zero-XSS-surface design.** Every other view in this
  app closes the class entirely by never parsing AI-returned HTML as markup; this one view accepts a
  sanitizer's word for it instead, because a formatting-only change has no other way to be visible. A
  DOMPurify bypass here is a real, if narrow, risk this app did not have before.

---

## Measuring it

`evals/` holds the harness for the one claim worth measuring: does a declared band survive into the
letter?

```bash
npm run eval:dry                       # prints the plan and the cost, sends nothing
npm run eval -- --n 1 --max-ops 20     # small-sample default
npm run eval -- --n 3 --arms both --resume
```

**Method.** Eight synthetic intakes, two per band, all fictional people. The drafter produces a letter;
a second, isolated SuperDocs chat pass infers its band blind. Drift is inferred rank minus declared rank
on a four-point scale. Positive drift means the letter reads warmer than the writer meant, which is the
failure this tool exists to catch, so it is reported signed rather than as absolute error.

The harness has a hard `--max-ops` stopping rule, appends to `evals/results/runs.jsonl` after every
letter so a killed run keeps what it paid for, and `--resume` continues from where it stopped.

**Results, `--n 1` (one letter per band, 16 letters total, 16 SuperDocs operations):**

| | Exact band match | Mean signed drift | Severe inflations |
| --- | --- | --- | --- |
| Baseline (band stated in the prompt only) | 85.7% | +0.143 | 0 |
| Audited (calibration gate applied) | 100.0% | +0 | 0 |

Full report, per-band breakdown and the stated limits of this measurement: [`evals/results/latest.md`](evals/results/latest.md).
Raw per-run data: [`evals/results/runs.jsonl`](evals/results/runs.jsonl) (committed, both re-generated by
`npm run eval`). Read this at n=8 total, not n=1000: one misread letter moves the mean noticeably, so
treat it as directional evidence, not a significance claim — the report says the same thing.

---

## AI disclosure

Built with heavy use of Claude, which is the point of the exercise. The architecture, the choice of
what to cut, the calibration design, and the limitations above are mine to defend. Two bugs in this
repository were found by tests rather than by reading: an injection pattern with a leading `\b` that
could never match a bracket-prefixed string, and a text extractor emitting double newlines on adjacent
block tags. Both are fixed, and both are why the tests exist.

---

Built by Shajahan for the SuperDocs Full-Stack AI Engineer task.
