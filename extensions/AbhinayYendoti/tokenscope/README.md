# TokenScope

A Word add-in that rewrites the paragraph you selected, then shows what that surgical edit
actually cost next to what regenerating the whole document would have cost.

Built for the SuperDocs Open Task List card **"Word selection rewrite with a live token
counter"** (Band S1 — surfaces: chat, API).

---

## What this build does

You select a paragraph in Word, type an instruction like _"Make this more concise"_, and
press Rewrite. TokenScope sends that as a **scoped** edit through the SuperDocs API, shows
you the proposed rewrite before anything is applied, and puts two numbers side by side: what
the surgical edit cost, and what a full regeneration of the same document costs.

The card's acceptance bar is that the counter is _measured, not asserted_. So both sides of
the comparison are real SuperDocs jobs, and every figure on screen carries a badge saying
whether it was **Measured**, **Tokenized** or **Estimated**. Nothing is invented — where a
number does not exist, the UI says "Not reported" rather than showing a zero.

## Who it is for

The card files this under _positioning demo_, and that is honest about who it serves: anyone
deciding whether in-document editing is worth it — an engineer evaluating the API, or
someone who needs the cost argument in numbers rather than adjectives.

## Why it exists

An AI document editor that regenerates the whole document on every turn pays for the whole
document on every turn. The cost of a one-paragraph change scales with the size of the file
it happens to live in, which is backwards: the edit did not get bigger, the document did.

Surgical editing breaks that coupling. That claim is easy to make and easy to hand-wave, so
TokenScope makes it falsifiable — it runs both operations against the live API, on the same
document, on the same day, and reports what each one actually did.

## How SuperDocs is used

Everything here is the live REST API at `api.superdocs.app/v1`. There is no mock and no
offline fallback: without a key the app starts, says the key is missing, and refuses to
rewrite rather than show invented numbers.

| SuperDocs surface                    | Where it is used                                                                                                                                                      |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POST /v1/chat/async`                | Both operations. Chosen over synchronous `/v1/chat` because that returns before a job record exists, and the job record is the only place a token count appears.      |
| `GET /v1/jobs/{job_id}`              | Polling — `compact=true` while running, one full read once settled, which is the API's own guidance for large documents. Also the source of the measured token count. |
| `POST /v1/chat/{session_id}/approve` | Applying one named change, and only when the user presses Apply.                                                                                                      |
| `GET /v1/agents/whoami`              | Tier and remaining monthly quota, shown in the pane header.                                                                                                           |
| Human-in-the-loop review             | `approval_mode: "ask_every_time"` on every request. `approve_all` is never sent.                                                                                      |
| Office.js                            | The Word host: reading the live selection and replacing the approved range.                                                                                           |

**Nothing is applied without approval.** The job pauses at `awaiting_approval`, the pane
shows the proposal marked _not applied yet_, and the document changes only when the user
presses Apply.

**Scope is verified, not assumed.** SuperDocs mints its own chunk ids, so returned changes
come back keyed to ids the client never sent. Each change is mapped back to the selection on
its original text. A change that cannot be mapped is treated as out of scope — shown to the
user, never offered for apply.

## How it works

```
Word selection (Office.js)   or the browser's own Selection API
        │
        ▼
rewrite instruction          the selection is delimited, not described, so the
        │                    model matches an exact string
        ▼
SuperDocs API                POST /v1/chat/async, approval_mode=ask_every_time
        │                    GET  /v1/jobs/{id}  (compact while running)
        ▼
proposed change              returned, displayed, still unapplied
        │
        ▼
token measurement            metadata.cumulative_tokens, plus the text the job
        │                    actually returned, tokenized
        ▼
whole-document comparison    the same instruction run as a real regeneration in
        │                    a throwaway session on a copy of the document
        ▼
review → Apply               POST /v1/chat/{sid}/approve, then the host edit
```

The API key lives only in a small Node server — a Word task pane is a browser, and the key
must never reach a browser bundle. That server is four routes and no state.

## Setup

**Prerequisites:** Node 20+, and a SuperDocs API key from
[use.superdocs.app](https://use.superdocs.app) → Settings → API keys. Word is optional.

```bash
cd extensions/AbhinayYendoti/tokenscope
npm install
```

Create `.env.local` from the template and add your key:

```bash
cp .env.example .env.local          # macOS, Linux, Git Bash
```

```powershell
Copy-Item .env.example .env.local   # Windows PowerShell
```

Then run it:

```bash
npm run dev      # http://localhost:5173
```

Everything runs from this folder. No command needs to be run from the repository root.

### Environment variables

Names only — see `.env.example` for the template.

| Variable               | Required | Purpose                                                                                                                   |
| ---------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| `SUPERDOCS_API_KEY`    | yes      | Your SuperDocs key. Read only by the server; never reaches the browser.                                                   |
| `SUPERDOCS_BASE_URL`   | no       | API root. Defaults to `https://api.superdocs.app/v1`.                                                                     |
| `SUPERDOCS_MODEL_TIER` | no       | `core` (default), `turbo`, `pro`, `max`. Both sides of the comparison use the same tier or the comparison is meaningless. |
| `PORT`                 | no       | Server port. Defaults to `8787`.                                                                                          |

`.env.local` is git-ignored. There is no key in this repository and never was.

## Usage

The demo document is synthetic and generated deterministically — no customer data is
involved anywhere in this build.

1. Open `http://localhost:5173`. The pane is on the left, a live document on the right.
2. The header shows _"N of 500 SuperDocs operations left"_. That is a real call to `whoami`,
   so if a number appears, your key works.
3. Click **Select it** above the document. It selects a deliberately overwritten paragraph:

   > Notwithstanding any provision of this agreement to the contrary, it should be noted
   > that the parties hereto have, over the course of the period under review, undertaken a
   > not insubstantial number of separate and distinct initiatives which…

4. Leave the instruction as _"Make this more concise"_ and press **Rewrite selection**.
5. Read the result, then press **Apply to document** if you want it.

Switch the document between **3 / 10 / 50 pages** with the chips and run the same rewrite to
watch the gap widen by hand.

### Running it inside Word

Word will not load add-in content over plain HTTP, even from localhost:

```bash
npm run word:certs      # one-time locally-trusted certificate for https://localhost
npm run word:validate   # checks manifest.xml against the Office schema
npm run dev             # now serves HTTPS on :5173
npm run word:start      # sideloads and opens Word (npm run word:stop to undo)
```

TokenScope then appears on Word's **Home** tab as **Token counter**. `npm run dev` never
installs a certificate on its own — without one it says so and falls back to HTTP.

## Output

A rewritten paragraph, and the cost of getting it:

- **The proposed rewrite**, next to the original, marked _not applied yet_
- **What SuperDocs reported it cost** — `metadata.cumulative_tokens` for each job
- **How much text had to be written** — tokenized from the text each job actually returned,
  plus how many sections each one changed
- **Savings**, as a percentage, for each of those comparisons

Pressing Apply approves that one change through SuperDocs and replaces the text in the
document. Nothing else moves.

## Benchmark

`npm run bench` generates documents at 3/10/50/100/300 pages and runs both operations against
each. Results are written to `bench/results.json` and rendered to
[`bench/RESULTS.md`](bench/RESULTS.md) — generated, never typed by hand, every row carrying
its job ids and timestamp.

| Document  | Sections changed | Written, surgical | Written, regenerated |           Saved |
| --------- | ---------------: | ----------------: | -------------------: | --------------: |
| 3 pages   |          1 vs 20 |         26 tokens |         1,124 tokens |          97.69% |
| 10 pages  |          1 vs 61 |         18 tokens |         4,589 tokens |          99.61% |
| 50 pages  |         1 vs 300 |         37 tokens |        19,822 tokens |          99.81% |
| 100 pages |         1 vs 599 |         32 tokens |        43,344 tokens |          99.93% |
| 300 pages |           1 vs — |         30 tokens |       never finished | see Limitations |

The surgical column does not move. That is the entire argument.

## Testing

```bash
npm test          # 93 tests
npm run typecheck
npm run lint
npm run build
```

None of those call SuperDocs, so they pass with or without a key. The API client tests stub
`fetch` rather than the client, so the real request is built, the real zod schemas parse the
response, and the real error mapping runs; the fixtures are trimmed copies of bodies the
live API actually returned.

## Limitations

Stated plainly, because a token counter nobody can check is just a number on a screen.

- **`metadata.cumulative_tokens` is not fully dependable.** It is not a running total despite
  the name — within a job it goes down as well as up. Across repeated runs the same 3-page
  rewrite reported 181,978 once and about 90,500 three times, and one 300-page run finished
  carrying no count at all. That is why a second measurement exists: the text each job
  actually returned, which is available on every job at every size.
- **A 300-page whole-document regeneration never completed.** Three attempts all reached 99%
  and stopped; SuperDocs' own watchdog eventually failed the last one as wedged. The surgical
  edit on the same 150,000-word document completed every time in 217–340 seconds. Recorded as
  a run that did not complete rather than converted into a percentage. This is a limit
  observed on a free-tier account at `core`, not a claim about the platform.
- **`o200k_base` is probably not SuperDocs' tokenizer.** Local counts are a reproducible
  measure of text volume, never a claim about billing, and they are only ever compared
  against each other.
- **The Word host is not covered by automated tests.** Office.js needs a real Word process.
  The logic it delegates to is tested through the demo host and the shared layer, and both
  hosts implement the same interface, but the Office.js calls in `src/host/word.ts`
  themselves are unverified.
- **The benchmark corpus is generated, not sampled** — deterministic prose, 500 words per
  page, one instruction, one model tier.
- **No screenshots or hosted demo** are included; the standalone mode is the demo, and it
  runs in a browser without Word.

## Credit

Built by **Abhinay Yendoti** for the SuperDocs engineering task.

AI coding assistance (Claude) was used throughout, as CONTRIBUTING invites. The measurement
design, the decision to stop trusting the provider's counter, and every number reported here
came out of running the live API and reading what came back.

Source repository:
[github.com/AbhinayYendoti/TokenScope](https://github.com/AbhinayYendoti/TokenScope)
