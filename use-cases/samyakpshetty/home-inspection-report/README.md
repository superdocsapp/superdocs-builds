# Home-inspection report builder

**I built this for the SuperDocs task**, on the [SuperDocs](https://use.superdocs.app) API.

A home inspector walks a property system by system and types what they see, in shorthand,
often one-handed on a phone in an attic. The person who has to read it is buying their first
house and has never seen an inspection report before. This closes that gap: findings grouped
by inspection system, each carrying a severity label, the inspector's notes and the
photographs that show it, assembled into a formatted field report on export — and the
language stays observational, because an inspection reports what was seen and recommends what
to do next. It never certifies the condition of a property.

![The review gate: what the inspector wrote, what SuperDocs proposed for the buyer, and the
observational-language rail's objection marked in the sentence where it
happens.](docs/review-gate.png)

## What it does

1. **An inspection is structured data.** A property, an inspector, and findings, each one
   belonging to exactly one inspection system and carrying a severity, notes and photographs.
2. **Photographs are cleaned before they go anywhere.** An oversized body is refused with a
   413 before it is read at all, the upload is then read in bounded chunks, the image is
   decoded to prove it is an image, **HEIC is accepted** (the iPhone camera default) and
   re-encoded to JPEG, the picture is **downscaled to 2048px** rather than refused for being
   big, and **EXIF is stripped** — a phone photograph of a house carries the house's GPS
   coordinates, and this report goes to buyers, agents and lenders.
3. **The report format is a Word document**, registered with SuperDocs and loaded back from
   it. The firm's letterhead, severity legend, standing preamble and limitations clause are
   theirs, in a file they can open and redesign.
4. **The report is rendered deterministically into that format.** Which system a finding
   appears under, and in what order, is decided by code from the system catalogue and the
   severity ranks. No model touches structure.
5. **SuperDocs rewrites the field notes** into something a first-time buyer can read, as
   proposed changes held for review rather than applied.
6. **Every proposal passes an observational-language rail before it can be approved.** A
   rewrite that certifies, guarantees, declares something safe or compliant, predicts a
   lifespan, estimates a cost or reassures the reader is refused, and the inspector's own
   words stand. The report loses polish, never content.
7. **The export is read back and checked.** Every system present and in catalogue order,
   every finding under its own heading, every severity label intact, every photograph
   embedded as real image bytes, no capability URL in the text, and no certifying sentence
   the system produced. Where the *inspector's own* wording carries a claim, that is reported
   with the phrase named and does not fail the export — their licence, their words.

## How it works

```mermaid
sequenceDiagram
    autonumber
    actor I as 👤 Inspector
    participant W as 🖥️ Interface
    participant A as ⚙️ API
    participant P as 🗄️ Postgres
    participant K as 🔧 Worker
    participant S as 🤖 SuperDocs

    I->>W: walk the property, system by system
    W->>A: findings, and photographs
    A->>A: refuse anything over 12 MB unread, then decode, HEIC → JPEG, 2048 px, strip EXIF, sha256
    A->>P: findings, and photograph bytes into a content-addressed store
    I->>W: Propose rewrites
    W->>A: POST …/prepare
    A->>P: enqueue a job
    A-->>W: 202 and a job id
    K->>P: claim one job, FOR UPDATE SKIP LOCKED, holding a renewed lease
    K->>P: skeleton held for this format hash and this provider?
    alt not held
        K->>S: register the format, if the account does not have it
        K->>S: "Load my '…' template… reproduce it exactly as saved"
        S-->>K: the format, as saved
        K->>K: read it back as a format — or fall back to the local copy, and say which
        K->>P: hold the skeleton against (format hash, provider)
    end
    K->>S: upload each photograph, skipping any hash already uploaded
    K->>K: bind the findings into that skeleton — deterministic
    K->>S: upload the report as one document
    K->>S: rewrite every finding note, in review mode
    S-->>K: one proposed change per note
    K->>K: language rail — a refusal is pre-decided, never offered as a choice
    K->>P: record every proposal with its verdict
    W->>A: poll the job, then read the proposals
    I->>W: Use the rewrite / Keep my wording, one at a time
    W->>A: POST …/decisions
    A->>S: approve — one call, every decision, refusals carrying their reason
    A->>P: the outcomes, and the approved wording against each finding
    I->>W: Export
    A->>S: export, then read the file back to confirm it carries the approvals
    A->>A: verify the finished bytes — grouping, order, labels, photographs, language
    A-->>I: the file, and what was found inside it
```

Two things in that diagram are the whole design.

**Structure is code; prose is the AI; presentation is the format.** *Bind the findings into
that skeleton* is deterministic; *rewrite every finding note* is not, and the line between them
is the architecture. Which system a finding belongs under, and in what order it appears, never
leaves `render/report.py` — so "grouped correctly by system", the one thing the card asks me
to confirm, is a property of the renderer rather than something to hope for. What the model is
asked for is the thing it is measurably good at: one narrow rewrite per note. That split was
tested rather than assumed — the experiment is in [`PROGRESS.md`](./PROGRESS.md).

**The gate is an operation, not a screen.** `prepare` → `decisions` → `export` are three HTTP
calls, and the interface is one driver of them. A person clicking and a program posting JSON
go through exactly the same path, and the rail sits behind all of it: a refused rewrite is
refused server-side, in `pipeline.decide`, whatever a client sends.

### The pieces, and where they are

| | |
|---|---|
| `domain/` | the typed model, and the catalogue read from `config/systems.yaml` and `config/severity.yaml` |
| `templates/registry.py` | registers each format with SuperDocs and asks for it back; validates what returns *is* the format |
| `templates/binding.py` | reads a format's worked example as the per-finding template, and fills it |
| `templates/authoring.py`, `wordcraft.py` | generate the three shipped `.docx` formats, so their design is reviewable in a diff |
| `render/report.py` | binds an inspection into a skeleton. Same input, same bytes |
| `render/pipeline.py` | `prepare` / `decide` / `export_recovering_session` — the three stages, and the settle-then-read-back on export |
| `phrasing/rail.py` | the observational-language rail: 12 refusing rules and 16 allow patterns, in `config/language_rail.yaml` |
| `photos/pipeline.py` | decode, HEIC → JPEG, downscale, strip EXIF, fingerprint |
| `superdocs/` | one typed protocol (`base.py`), the live client, the deterministic fake, and an offline exporter |
| `store/` | `db.py`, `blobs.py` (photograph bytes), `jobs.py` (the queue), `migrate.py` (ordered, immutable migrations) |
| `verify/exports.py` | opens the finished PDF or DOCX and reports what is actually in it |
| `api/app.py`, `worker.py` | the HTTP surface, and the container that does the slow part |
| `frontend/` | React and TypeScript; hash routing, `#/i/<id>/walk\|review\|export` |

Not in the diagram, because it is the uncommon path: if the SuperDocs session is gone by the
time someone exports — a restart, or a report signed off weeks ago — the document is
re-rendered from our own database and re-uploaded, and the response says `X-Report-Source:
rebuilt` rather than `session`. Nothing is lost, because every finding, approved rewrite and
photograph is ours; neither upload nor export costs an operation, which is what makes that the
cheap answer rather than a clever one.

## Running it

Everything runs in Docker, so the checks below behave the same on any machine.

```bash
make demo
```

That is the one command. It builds the sample property end to end on deterministic fakes —
**no API key, no network, no cost** — writes a real PDF and DOCX into `exports/`, then opens
those files and verifies them:

```
Building 14 Alder Lane, Fairhaven, FH8 2QR — 8 findings, 8 photographs, provider=fake, format=buyer_summary
  format: 'Home inspection format — buyer_summary [600b87c6]' — skeleton loaded from SuperDocs
  photographs: 8 uploaded, 0 reused
  rewrites: 8 proposed, 6 approved, 2 refused by the language rail
    refused — 'for safety' (safety); 'functioning correctly' (scoped)
    refused — "typical for the home's age" (reassurance)
  operations: 1 charged, 9998 remaining
  wrote exports/14-alder-lane-2026-08-12.pdf (165,192 bytes)
  PDF
    [PASS] every inspection system appears — 6 systems
    [PASS] systems appear in catalogue order
    [PASS] every finding is under its own system — 8 findings
    [PASS] severity labels are present — 4 distinct labels
    [PASS] photographs are embedded in the file — 8 embedded, 8 expected
    [PASS] no certification language the system produced
    [PASS] no photo URLs leaked into the document text
```

For the interface an inspector actually uses:

```bash
docker compose up
```

Postgres, the API and the browser front end at **http://localhost:5174**. Still no API key —
`PROVIDER` defaults to the deterministic fake, so a fresh clone gives you a working
application rather than a login wall.

A fresh database is empty, so there is nothing to look at. This fills it:

```bash
make seed
```

The sample property, eight findings across all six systems, eight photographs — written
through the same pipeline the browser uses, so what you see is what the application really
stores. `make seed` is repeatable; it replaces the seeded property rather than duplicating
it.

```bash
make check
```

ruff + `ruff format --check` + `mypy --strict` + the full test suite + the front end's
TypeScript: **229 tests, none of which need an API key.** A further 32 need a Postgres and
skip without one; `make test-db` runs those against the database `docker compose up` starts.

No test can reach the real service, whatever your shell is set to: the one test that does is
deselected unless asked for by name (`pytest -m live`), and everything else has `PROVIDER`
pinned to the fake with the key cleared. Running the suite costs nothing, and that is
measured rather than assumed.

Other targets: `make verify` re-checks the files already in `exports/`, and
`docker compose run --rm --no-deps api python -m inspection_report.cli formats` lists the
report formats.

<details>
<summary><b>Running it live against the real API</b></summary>

Get a key from `use.superdocs.app` → Settings → API Keys, then:

```bash
cp .env.example .env     # set PROVIDER=live and SUPERDOCS_API_KEY=your-key-here
docker compose run --rm --no-deps -e PROVIDER=live api python -m inspection_report.cli demo
```

That is the command-line path. To run the **whole application** against the real service —
the interface, the worker and the round trip an inspector actually walks through:

```bash
PROVIDER=live SUPERDOCS_API_KEY=your-key-here docker compose up -d
```

A report costs about two operations: one to load the registered format, one for the rewrite
pass. The loaded format is then held against its content hash, so the second report of the
day pays only for the rewrite. Exports cost nothing. The interface says which of the two it
used, and says so when it has fallen back to the local copy instead.

The key is read server-side only and never reaches a browser. Choose the precision/speed
tier with `--model-tier core|turbo|pro|max`; it is a parameter rather than a constant,
because the right default for a legal document is not the right default for a quick pass.

</details>

## The interface

Three stages, because the gate is a real stage and not a modal: **the walk**, **the review**,
**the export**. Each is a URL, so a property can be bookmarked and a reviewer can be sent
straight to the gate.

![The walk: the severity × system grid showing the shape of a property at a glance, and the
findings recorded under each system.](docs/the-walk.png)

The grid is the one view that answers the question everybody asks first — where are the
problems, and how bad. An empty row says nothing was observed in that system, which is not
the same as it having been skipped, and the report says so too.

**This tool makes a printed document, so it is set like one.** An inspection report has a
title page, standing text, numbered sections and a severity legend; building the interface to
look like the artefact it produces is the fastest way to understand what you are assembling.
Sections are numbered on an editorial grid, with a narrow rail carrying the number and the
count beside the column you read.

Three type voices, each with a job, so you can tell what kind of thing you are looking at
before you read it:

| voice | carries |
|---|---|
| serif | the document — the property, section headings, the buyer-facing prose |
| sans | the interface — buttons, fields, anything you operate rather than read |
| mono | the field — what the inspector typed, severity codes, counts, labels |

That pairing does real work at the review gate: the inspector's shorthand is set in mono and
the proposed rewrite in the report's own serif, so the transformation is visible before a word
is read. All three are system stacks — an inspector loads this in a basement on one bar of
signal, and a webfont is a render-blocking round trip for a typeface nobody would notice.

Colour means severity and nothing else. That rules out the usual way of making an interface
look designed — a brand accent, a coloured header — which is exactly why this one is built
from type, rule and grid. On a document where a buyer has to spot "recommend prompt
evaluation" at a glance, a decorative colour competing with the one that carries meaning is
not a style choice, it is a hazard. Both themes are real: an attic at midday and a crawlspace
both happen, and the severity hues are re-picked for a dark ground rather than inverted.

## Report formats

Three ship, and switching between them is a data change:

| Format | For | Photographs |
|---|---|---|
| `buyer_summary` | the buyer, as the primary document | yes |
| `full_technical` | a specialist quoting remedial work | yes |
| `repair_priority` | a working list for collecting quotes | no, by design |

**A format is a `.docx`** — a Word document with letterhead, the severity legend, the standing
preamble, a section per inspection system and the limitations clause. A firm opens one in
Word, changes it, and drops it back in.

They are **set, not typed**: a masthead closed by a heavy rule, small-caps letterspaced field
labels, section headings on their own hairlines, a severity legend where each level carries
its own colour, and a footer with the property and the page number. That design is generated
from code rather than committed as an opaque binary, so a change to it is reviewable in a
pull request and the catalogue stays the single source of the systems and the scale.

Colour in the document is spent on severity and nothing else — the headings are a deep slate,
a neutral rather than a hue — because the severity is the one thing a buyer has to pick out at
a glance.

The markers are things a person types, not markup:

```
[firm name]  [property address]  [inspector]  [date of inspection]
[systems inspected]  [system summary]  [findings]
[severity label]  [location]  [observation]  [recommendation]
[photograph]  [caption]
```

A format also carries **one worked example** showing how a single finding is recorded. The
binder reads that example *as* the per-finding template and then removes the section from the
finished report — so a firm changes the layout of every finding by editing one example in
Word, with no code change. What the verifier holds a format to is read from the format
itself: the repair-priority list shows no photograph in its example, so photographs are not
expected in it.

Binding is strict in both directions. A format that uses bracketed text which is not a token
is an error naming the typo and listing the vocabulary, and a token nobody fills is an error
rather than a gap in a document a buyer reads.

The inspection systems, the severity scale and the language rail are all data too, in
`config/`. Adding a seventh system, grading on four levels instead of five, or operating
under a firm's own wording rules is a change to YAML and to nothing else.

## Removing things

An inspection, a finding and a photograph can each be deleted, and each asks first — in
place, not in a dialog, and not in red, because colour means severity here and nowhere else.
The question names what goes: *"Delete 14 Alder Lane and its 8 findings? This cannot be
undone."*

Deleting an inspection is refused while a review is in flight, since the worker is holding
it. Blobs are **refcounted, not cascaded**: a key is a content hash, so two findings that
photographed the same thing share one file, and the bytes are reclaimed only when the last
row referencing them is gone.

## Long work does not block a request

Asking SuperDocs to rewrite every finding takes as long as it takes — their own guidance says
thirty seconds to several minutes. So `prepare` enqueues a job and answers **202 immediately**;
a separate worker does the work and the interface polls. Closing the page or reloading loses
nothing, and a reload rejoins a review already in flight.

The worker is its own container because a background task inside the API dies with a deploy,
and this work has been paid for. It claims with `FOR UPDATE SKIP LOCKED`, so scaling is a
replica count. It holds a lease it renews while working; if it dies, the job is **failed, not
retried** — re-running something that may already have spent an operation would spend another,
and nothing was applied, so the honest answer is to say it stopped and let a person start
again. One live review per inspection is enforced by a partial unique index.

## Where photographs live

Bytes go to a blob store; the database keeps a key. The key **is** the photograph's sha256,
which the build already used as its identity, so two findings sharing a photograph share one
file and a retry after a crash overwrites a byte-identical blob rather than growing the
store. A filesystem store ships and is backed by a named Docker volume; swapping in S3 or GCS
is one class satisfying `put` / `get` / `exists`.

Keys are validated as hex hashes before they touch the filesystem, so a key can never be read
as a path. Rows written before this still carry their bytes and still serve — the read path
falls back to the column.

## Schema changes

The schema is a set of ordered SQL files in `migrations/`, applied once each and recorded
with a checksum in `schema_migrations`. A migration that has run is immutable — if the file
changes, the next start fails and names it, rather than leaving two databases disagreeing
about what `0002` means. Two API processes booting together take an advisory lock, so one
applies and the other finds nothing to do.

To change the schema, add the next numbered file. Nothing else needs editing; the runner
picks it up on the next start.

## SuperDocs surfaces used

| Surface | How |
|---|---|
| **Templates** | each report format registered, then **loaded back and built on** — delete it from the account and no report can be produced |
| **Upload** | the rendered report goes up as one document |
| **Chat** *(review mode)* | rewrites each field note for a first-time reader, held for approval |
| **Approve** | one call per job, carrying every decision including the rail's refusals |
| **Export** | PDF and DOCX with real options — paper size, margins, filename |
| **Images** | every photograph uploaded and embedded in the document by URL |

Built on the REST API. The brief treats REST and MCP as interchangeable; REST was the shorter
path to the four calls.

## Calls I made

Where the brief or the API was silent, I made a call and recorded it here.

- **Structure is code; prose is the AI; presentation is the format.** I tested the opposite
  design rather than assuming this one. Asked to assemble the whole report from a registered
  format and eight supplied findings, SuperDocs' AI applied one unrelated change, charged an
  operation, and replied asking for the findings that were in the message — while the same
  session, same document and same approval mode applied three scattered replacements
  flawlessly and expanded one placeholder paragraph into a six-paragraph section. The
  boundary is the scope of a single request, not message size or instruction-following. So
  the AI keeps the narrow, targeted rewriting it is measurably good at, and the one thing the
  brief asks me to confirm stays a guarantee rather than a hope. The measurements are in
  [PROGRESS.md](PROGRESS.md).
- **The markers are bracketed text because HTML comments do not survive an upload.** The
  first design marked repeatable regions with `<!-- region:system -->`; upload parses a
  document into chunks and drops comments, so a registered format came back without the
  markers the binder needed and the round trip could never complete. Bracketed text is not
  markup, so nothing strips it — and it reads as an instruction to whoever is authoring the
  format, which a comment never did.
- **We ship the formats, and they are editable.** The premise is that existing inspection
  reports are not formatted for a first-time buyer, so binding data into a firm's existing
  report would reproduce the problem. A builder that requires you to supply the format is a
  mail-merge engine. Three ship; because they are Word documents, a firm can then make them
  their own.
- **The rail governs generated text, never the inspector's own.** They are the licensed
  professional and the report is theirs. What this system may not do is put certification
  language in their name.
- **Refusing valid work is treated as a failure of equal weight.** Real inspection vocabulary
  is allow-listed, and terms that are honest when tied to the moment of observation are
  checked for that scope rather than banned — "operated normally when tested" passes where
  "operational" does not. An early version of the rail refused the report's own disclaimer
  and the ordinary English verb in "warrants evaluation"; a test now holds every rule to the
  wording it recommends.
- **A photo URL is a capability, not an identifier.** The image endpoint returns a stable
  `url` and a signed `view_url`, but the stable one is readable with no credentials at all
  and does not expire. It is scrubbed from every log line, refused by the model's own
  `__str__`, and HTML export embeds image bytes so no exported file carries one.
- **A system with no findings still gets its section**, and says that nothing was observed.
  Silence about a system reads as "not inspected", which is a different and more dangerous
  claim.
- **An export is not trusted on its word** — see below.

## What it guarantees

- **Grouped, provably.** The verifier opens the finished PDF and DOCX and checks the
  structure against the catalogue, rather than checking the HTML that was sent.
- **Never certifies — and says whose words it was.** The rail runs on every proposal before
  approval *and* over the exported bytes afterwards, but the finished file separates a claim
  the *system* produced (a failure, because that is the thing this build exists to prevent)
  from one the *inspector* wrote (reported, never failed, because the gate promised their
  wording is kept exactly as written). Conflating them was a real bug: an inspector typing
  "is safe" got their report marked failed one screen after being told it would be kept, and
  a failure nobody can resolve is one everybody learns to ignore — which is precisely how a
  generated claim would slide past.
- **Never silently stale.** Exporting immediately after approving can return the
  **pre-approval** document with a 200 and no warning — I hit this on a live run, where the
  PDF carried the original text and a DOCX of the same session one second later carried the
  approved rewrites. Every approved rewrite is now read back out of the exported file and the
  export is repeated until they are present. Exports cost nothing, which is what makes
  re-reading the right answer.
- **Concurrent writes do not erase each other.** Recording a finding inserts one row rather
  than rewriting the inspection's whole set from a snapshot, and only a caller that owns the
  whole set may prune. Six requests arriving together used to leave two findings out of
  eight; they all land now, and a test holds it against a real database.
- **A finished report stays exportable.** The session is where the document lives on
  SuperDocs' side, and a session does not outlive a restart. Every finding, every approved
  rewrite and every photograph is in our own database, so the document is rebuilt from there
  and exported rather than failing on work that is already signed off — and the response says
  which path produced the file.
- **Idempotent where it costs money.** A photograph's identity is the hash of its cleaned
  bytes, so a crash and re-run re-uploads nothing. A format is registered once per version,
  by content hash.
- **Untrusted input is treated as such.** A body over the ceiling is refused before it is
  read, the upload is read in bounded chunks, decode-verification rather than trusting an
  extension, EXIF stripped, every query parameterised, everything a person typed escaped
  before it becomes markup, and rejection messages that never echo file content.
- **No secret in code, logs or history.** `.env` is git-ignored; only `.env.example` with
  placeholders is tracked. The API key is held server-side and never reaches the browser,
  which is also why photographs are served from `/api/photos/{id}` rather than by handing the
  browser the URL SuperDocs returned.

## Limitations

- **The offline exporter is a stand-in.** With `PROVIDER=fake` the PDF and DOCX are written
  locally so the demo and the tests are real end to end. It carries emphasis, size and
  alignment, but it is a simple renderer — no page furniture, no widow control, and its line
  breaking is its own. The live path uses SuperDocs' exporter, which is what the formats are
  designed around and which reproduces the Word document properly.
- **One firm, one report at a time.** No multi-property scheduling, no job queue, and no user
  accounts beyond a single firm.
- **The format vocabulary is fixed.** A firm can change the layout, the wording and the design
  freely, but the thirteen tokens above are the ones this build fills. A format wanting a
  fourteenth needs a code change.
- **Photographs are not analysed.** Deliberate: asking a model to describe a property from a
  photograph invites exactly the over-claiming this build exists to prevent. The photograph is
  evidence the reader looks at; the claim stays the inspector's.
- **Attribution is what the inspector typed.** Nothing here verifies that a finding is
  correct, and nothing should be read as doing so.

Engineering notes and the full assumption log are in [PROGRESS.md](PROGRESS.md).
