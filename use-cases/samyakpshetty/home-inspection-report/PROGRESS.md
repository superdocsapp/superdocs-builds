# Engineering notes

The assumption log for this build, and the reasoning behind the calls I made. The README says
what it does; this says why it is shaped that way.

## The three decisions everything else follows from

**Structure is code, prose is the AI, presentation is the template.**

I researched the templates surface before designing around it, and found there is no endpoint
that applies a saved template to a document. Templates are *AI-referenced*: you register one,
and the AI loads it into a session when you ask for it by name. I confirmed this works — I
registered a report format with three sentinel strings in it and asked the AI to draft from
it by name, and all three came back in the drafted document.

That settled the architecture. If the AI owns structure, then "grouped correctly by system" —
the one thing the brief asks me to confirm — becomes something I hope for. So the report is
rendered deterministically from typed data, and the model is given the job it is actually
reliable at: turning field shorthand into sentences a first-time buyer can read. That was a
judgement at first. It is now a measured result — see the experiment below.

**A report format is a Word document.** Not HTML with markers in it. This build exists
because inspection reports are not written for the person reading them, and a format nobody
can open is a format nobody will redesign. So `templates/` holds `.docx` files: letterhead,
the severity legend, the standing preamble, a section per inspection system, the limitations
clause. A firm opens one in Word, changes it, and drops it back in.

The markers are things a person types, not markup: bracketed tokens like `[findings]`,
`[severity label]`, `[observation]`, `[photograph]`. That is not a stylistic choice. The
earlier design marked regions with `<!-- region:system -->`, and **upload strips HTML
comments** — verified, four sent and none returned, in the same request where `class`
attributes survived. A format marked up that way could never come back from the service with
the markers the binder needed, so the templates surface was registered-and-verified rather
than load-bearing. Bracketed text is not markup, so nothing strips it, and the round trip now
completes: the format registers, comes back exactly as saved, and the report is built on what
came back. Delete it from the account and no report can be produced.

**A format also owns how a finding looks.** It carries one worked example — the severity
label and location, what was observed, the recommended next step, the photograph and its
caption — and the binder reads that example *as the per-finding template*, then removes the
section from the finished report. So a firm changes the layout of every finding by editing
one example in Word. What this build still owns is which system a finding goes under and in
what order; the format owns everything about how it reads.

**A format is designed, and the design is asserted.** A report is the only thing a buyer,
an agent or a lender ever sees, so the shipped formats are set rather than typed — rules,
letterspacing, small-caps labels, severity colour, a numbered footer. Two things were learned
making that hold. A table cell's *fill* survives the trip through SuperDocs but its *width*
does not, so the severity swatch arrived as a slab across a third of the page; it is a
coloured glyph now, because run colour survives every renderer. And small caps on a severity
label renders it upper-case, which made the export verifier fail to find a label it was
holding the document to — presentation does not get to break a guarantee, and a test now
refuses small caps on any string the verifier checks.

**We ship the formats.** The brief's premise is that inspection reports are not formatted for
someone who has never read one. A builder that asks a firm to upload its existing report and
binds data into it would faithfully reproduce that problem, and a builder that requires you
to supply the format is a mail-merge engine. So three formats ship with the product, a firm
chooses among them, and — because they are Word documents — can then make them their own.

**The language rail is code, not a prompt.** The brief states the language requirement rather
than suggesting it, and a prompt is a request. It is also not hypothetical: on the first live
drafting sample, asked only to draft a report, the AI produced "recommend replacement **for
safety**", "older but **operational**", and "**typical for the home's age**" — a safety
assurance, a functional verdict, and a reassurance no inspector gave. Those three sentences
are now the regression suite.

## The experiment that decided the architecture

The three decisions above were reasoned from how the templates surface behaves. Reasoning is
not evidence, so before committing to them I built the opposite design and measured it: let
SuperDocs' AI assemble the whole report from a registered format, and let the export verifier
be the guarantee instead of the renderer. If the AI groups correctly, the verifier passes and
the deterministic renderer is unnecessary machinery.

It does not, and the way it fails is worth recording.

| What was asked, all on one session, one document, one approval mode | What happened |
|---|---|
| Load a registered `.docx` format into the session | **Works.** Returned exactly as saved — headings, bold, italics, the legend, the standing text, chunk ids assigned. One turn is a *load*, not a draft: it edits nothing |
| Three unrelated replacements, sentinels at char 172, 2,938 and 5,703 of a 5,716-char message | **3/3 applied.** Long messages are not truncated |
| One system, two findings: replace one placeholder paragraph with six new ones (172 → 610 chars) | **Applied**, correctly placed, and the other five sections untouched. Surgical |
| Six systems, eight findings, in one request | **Nothing.** One unrelated deletion applied, one operation charged, and a reply asking for the findings that were in the message |

So the boundary is not message size, not instruction-following, and not the ability to author
new structure. It is the **scope of a single request**. Narrow asks are precise; a
whole-document authoring ask collapses, and says something misleading while it does.

Three things follow, and they are the shape of the build:

- **The report format is a real `.docx`.** This half of the alternative design was right and
  is now proven end to end: a Word document a firm could open, edit and recognise, registered
  with SuperDocs, loaded back with its structure intact. It replaces the HTML formats marked
  up with `<!-- region:system -->` comments, which could never have worked, because upload
  strips HTML comments (finding 6). The bracketed placeholder paragraphs a human writes in
  Word survive the round trip and are what the binding engine anchors on — the marker is now
  something an author can see and type, rather than an invisible comment.
- **Assembly stays deterministic.** Not because the AI grouped things wrongly — it never got
  far enough to group anything — but because the one operation that reliably does this work
  is a narrow, targeted edit, and a report needs the whole structure at once. Doing it
  through the AI would cost one operation per system and put the card's single stated
  requirement at the mercy of the request that failed above.
- **The AI keeps the job it is measurably good at:** rewriting one chunk at a time, which is
  what the product says it is for. That is one operation per report, gated by a human, with
  the rail in front of it.

The export verifier stays exactly as it is. It was written to prove the renderer's output and
it now also stands as the check on anything the AI touched.

## Calls made where the brief or the API was silent

- **The rail governs generated text only, never the inspector's own words.** They are the
  licensed professional and the report is theirs. What this system may not do is put
  certification language in their name. **The export verifier has to honour the same
  distinction**, and originally did not: it ran the rail over the whole finished file, so an
  inspector who wrote "is safe" got `verified: fail` one screen after the gate told them
  their wording was kept exactly as written. Attribution fixes it — a phrase traceable to a
  finding's own observation or recommendation is reported and never fails; anything else got
  into the document another way, and that is the failure worth having. Conflated, the second
  hides behind the first.
- **Deleting asks once, in place, and never in red.** An inspection, a finding and a
  photograph can each be removed, and the question names what goes rather than saying "are
  you sure". Not a `confirm()` dialog: on a phone, mid-job, a modal appears over the thing
  you were looking at. Not red either — colour is spent on severity, so the weight of a
  destructive action comes from the sentence and from having to say it twice. Blobs are
  refcounted rather than cascaded, because a content hash is shared by design.
- **A refused rewrite leaves the original standing** rather than blocking the report. The
  document loses polish, never content.
- **Refusing valid work is a failure of equal weight to permitting a bad claim.** A rail that
  flagged "safety glazing" or "no leaks were observed" would be switched off within a week.
  So real vocabulary is allow-listed first, and terms that are honest when scoped to the
  moment of observation are checked for that scope rather than banned.
- **Every system gets a section, including one with nothing in it**, which says that nothing
  was observed. Silence about a system reads as "not inspected" — a different and more
  dangerous claim.
- **A photo URL is a capability, not an identifier** (see below), so only the stable form is
  stored, it is scrubbed from every log line, and the model's own `__str__` refuses to print
  it.
- **EXIF is stripped from every photograph.** A phone photograph of a house carries the
  house's coordinates, and this document goes to buyers, agents and lenders.
- **Repair pricing is refused by the rail.** A number in the report reads as an estimate the
  inspector is standing behind; that belongs in a contractor's quote.
- **Photographs are not analysed by a model.** Asking one to describe a property from a
  photograph invites exactly the over-claiming this build exists to prevent.
- **`model_tier` is a parameter, never a constant**, as the integration guidance asks. The
  right default for a legal document is not the right default for a quick pass.
- **The interface is set like the document it produces.** Colour is spent entirely on
  severity, which rules out the usual way of making an interface look designed, so this one
  is built from type, rule and an editorial grid instead: numbered sections, a rail carrying
  the number and the count, and three type voices with distinct jobs — serif for the
  document, sans for the controls, mono for field data. The last one earns itself at the
  review gate, where the inspector's shorthand is mono and the proposed rewrite is the
  report's own serif, so the transformation is legible before a word is read.
- **The stage is a URL.** `#/i/<id>/walk|review|export`. Holding it in component state alone
  meant a property could not be bookmarked, a reload dropped you at the list, the back button
  did nothing, and a reviewer could not be sent to the gate. Hash rather than path, because
  this ships as a static bundle.

## What the API actually does, where it differs from its documentation

Everything here was established by calling the endpoint and reading the response. Each one is
reported to SuperDocs.

- **`export` immediately after `approve` can return the pre-approval document.** The most
  serious of these. On a live run, `approve` returned 200; the PDF exported two seconds later
  carried the original text while a `.docx` of the same session one second after that carried
  the approved rewrites. Re-exporting minutes later returned the approved text in both, so it
  is a timing race rather than a difference between exporters. **Mitigation:** every approved
  rewrite is read back out of the exported bytes and the export is repeated with backoff until
  they are present. Exports cost nothing, which is what makes re-reading the right answer; if
  it never converges the mismatch is logged at ERROR rather than reported as success.
- **An uploaded image is world-readable.** The endpoint returns a stable `url` and a signed
  `view_url` with a 24-hour expiry, which implies access control. Fetching the plain `url`
  with no authorization header at all returns the image. The signature is decorative, and the
  URL is a permanent capability.
- **`class` survives upload; custom `data-*` attributes do not.** So findings are targeted by
  class and never by an id of our own. The fake strips `data-*` the same way, because a fake
  more permissive than the service is how a design comes to depend on something that is not
  there.
- **A completed job hides its document.** `document_html` is `null`; the content is at
  `result.document_changes.updated_html`.
- **`approve` keys on `change_id`, not `chunk_id`,** and closes the job it is called on, so a
  job's decisions are collected and sent once.
- **`/v1/users/me/usage` and `/limits` reject API keys** with a 401 saying they need a signed-in
  user session — while being published under the same bearer scheme as everything else.
  **`GET /v1/users/me/promotions` does accept an API key** and reports the promo bucket's
  `ops_remaining`, so a balance costs nothing to read. An earlier version of these notes
  claimed you had to spend an operation to find out; that was wrong, and it was wrong because
  I had not tried `promotions`.
- **`session_id` on the templates upload does nothing.** The shared request schema documents
  it as loading the template into a session; exporting that session returns "No document
  loaded in this session."
- **HTML comments do not survive an upload.** The parser drops them. Four sent, none
  returned, in the same request where `class` and `{{placeholder}}` both survived. This
  invalidated the first format design and is why formats are Word documents with bracketed
  tokens now.
- **A delete-type change carries `new_html: null`.** Not every proposed edit is a
  replacement, and typing the field as a string made a whole job — already charged for —
  unparseable. Normalised in one place, with `operation` still naming the kind of edit.
- **A whole-document authoring request applies nothing**, and replies asking for the data it
  was given. Narrow edits are surgical; see the experiment above.

## Things I got wrong, and what fixed them

Kept because the fixes are the interesting part.

- **The rail refused the report's own disclaimer.** "…is not a certification, warranty or
  guarantee…" tripped three rules, and "warrants evaluation" — the ordinary English verb —
  tripped a fourth. The first fix listed the allowed phrasings, which would have reopened on
  the next phrasing. The second recognises the verb by what it governs anywhere in the
  sentence, and a test now holds every rule to the wording it recommends.
- **An early `absolute_negative` rule banned the exact sentence its own guidance suggested.**
  One scoped rule now covers the whole class of negative findings rather than a list of nouns
  that goes stale.
- **The verifier located systems by searching the flattened text**, which found their names in
  the "what was inspected" sentence and put every section boundary in the wrong place. It is
  line-oriented now, anchored on headings.
- **It also missed a phrase in the PDF that it found in the .docx**, because a PDF export wraps
  a paragraph across lines. It searches the joined text and maps back to a line.
- **Word stores `Heating &amp; Cooling`,** so a heading plainly present was reported missing.
- **Inserting photographs at full resolution** made an 8.3 MB file out of 57 KB of image data.
- **The application never asked SuperDocs for the format.** `registry.materialise` — the round
  trip this design rests on — was called only from the CLI. The API and the worker both used
  `_template_html`, which the function's own docstring calls the *fallback*. So `make demo`
  did the round trip and the running application, the one an inspector uses, did not, while
  the README described the round trip as the architecture. It now goes through
  `_materialised_template`, cached in Postgres against the format's content hash so it stays
  one operation per format version, and both the job result and an `X-Report-Template` header
  say which of `superdocs` / `cache` / `local` produced the skeleton. Found by being asked
  whether the template was really handled in SuperDocs — it was not.
- **The fake was a dict in one process, and the work runs in two.** Moving the rewrite pass to
  the worker silently defeated the `_FAKE` singleton, whose comment names this exact failure:
  the worker created the job, the API received the approval, and the API's fake had never
  heard of the job. Every approval in the running application failed with
  `unknown job 'job-0001'` — while 218 tests and `make demo` stayed green, because both do
  the whole round in one process. The fake now shares sessions, jobs and its id counter
  through a locked file on a volume when `FAKE_STATE_DIR` is set. Rule 1 of that module said
  the fake must never be more forgiving than the service; this was the other direction, which
  is just as wrong.
- **`get_conn` reported every error as a database outage.** A dependency that yields is also
  where FastAPI re-raises whatever the endpoint threw, so its catch-all turned request
  validation errors into 503 "the database is not reachable" while the database was answering
  every other call in the same second. It cost me ten minutes on the wrong system before I
  checked `pg_stat_activity` and found six connections of a hundred in use.
- **The interface showed the fake's invented operations balance.** The offline fake counts
  down from 10,000, so the screen read "9,999 operations left" while the real promotional
  balance was 9,942 — formatted identically, with nothing saying which SuperDocs had
  answered. A figure nobody can tell is made up is worse than no figure; it is only shown as
  a balance when it is one.
- **The suite could spend money, and said it could not.** `pytest` never deselected the
  `live` marker, so the one test that hits the real API ran in the default suite whenever a
  key happened to be in the environment — which is exactly the case while checking a live run.
  It skipped itself without a key, so the marker's own description ("never in the keyless
  suite") read as true for as long as nobody was in a position to disprove it. Measured
  rather than assumed: `make check` from a live terminal cost one operation, and now costs
  none. `not live` is in `addopts`, `conftest.py` pins `PROVIDER=fake` and clears the key for
  everything unmarked, and `pytest -m live` still opts in by name.
- **The API had no tests at all.** 218 of them, and not one went through a route. Both of the
  bugs above lived in that gap and were found by using the running application, not by reading
  it. `tests/test_api.py` closes it.

## Verification

- 229 tests in the keyless suite and 32 more against a real Postgres, none needing an API
  key. No `unittest.mock`, no patching: a deterministic fake that satisfies the same typed
  protocol as the live client, and real image bytes generated by a committed script.
- `make check` is ruff + `ruff format --check` + `mypy --strict` + the suite + the front
  end's TypeScript, in Docker.
- The whole path proven live against the real API: photographs uploaded, report uploaded,
  rewrites proposed and gated, one approve call, PDF and DOCX exported with all photographs
  embedded, and the same verifier run over the live-exported bytes.
- The exported PDF was opened and looked at, not just parsed.

## Is this production ready? Four of the five gaps are closed

The domain logic is production-grade: structure is deterministic, the rail is enforced in
code, the export is verified by reading the finished bytes, photographs are cleaned, and the
data-loss and concurrency faults found by testing are fixed and covered against a real
database. What is not ready is the operational shape around it.

1. ~~**`prepare` blocks an HTTP request for as long as the AI takes.**~~ **Fixed.** It
   enqueues and answers 202 in about ten milliseconds; a separate worker claims the row with
   `FOR UPDATE SKIP LOCKED` and the interface polls. A separate process rather than a
   background task inside the API, because a background task dies with the deploy and this
   work has already been paid for. The worker holds a lease it renews; when it dies the job
   is **failed rather than retried** — re-running something that may already have spent an
   operation would spend another, and nothing was applied, so the honest answer is to say it
   stopped. One live job per inspection is a partial unique index, so two API processes
   cannot both accept one.
2. **There are no migrations.** `apply_schema` is `CREATE TABLE IF NOT EXISTS`, so an
   existing deployment never gets a new column — the table already exists and the statement
   does nothing. Fine for a fresh clone, unusable for a second release. Wants Alembic.
3. ~~**Photographs are full-resolution BYTEA in Postgres.**~~ **Fixed.** Bytes live in a blob
   store keyed by their content hash — which the build already treated as a photograph's
   identity, so two findings sharing one photograph share one file. A filesystem store ships
   and backs the default deployment; S3 or GCS is a class satisfying the same three methods.
   The old columns are kept nullable and the read path falls back to them, so migration 0002
   is a migration rather than a data loss. Unreferenced blobs are not reclaimed — a key can
   be shared, so that is a sweep, and it is not written.
4. ~~**The 8 MB upload cap is below what modern phones produce.**~~ **Fixed**, and it was
   worse than a cap: HEIC — the iPhone camera default since iOS 11 — was refused outright.
   HEIC is decoded and stored as JPEG, uploads are accepted to 25 MB and downscaled to
   2048px before storage.
5. **One firm, no multi-tenancy.** The queue and the workers arrived with (1) — scale is a
   replica count, and two are safe. What remains is multi-tenancy, and that is not a missing
   feature so much as a missing prerequisite: without authentication there is nothing to scope
   a tenant *to*, and authentication is deliberately out of scope here. Metrics beyond
   structured logs and per-stage timings are also absent.

None of these are hidden by the interface — `/ready` reports whether the database is actually
reachable, distinct from `/health`, which stays a liveness check so a database blip does not
turn into a restart loop.

## Not built, and why

- **An MCP surface.** The card names the REST API and the brief treats the two as
  interchangeable, so this is a deliberate omission rather than an oversight. The seam that
  would carry it already exists — `SuperDocsClient` is a typed protocol and the API layer is
  thin — but adding a second transport to a build that has one honest consumer would be
  surface for its own sake.
- **Streaming uploads.** An oversized request is refused before it is read and the rest is
  read in bounded chunks, but what is accepted is held in memory rather than streamed to
  storage. Correct for phone photographs under the service's own 10 MB ceiling; anything
  larger would need a streaming path.
- **Multi-property scheduling, a job queue, and user accounts beyond a single firm.** One
  firm, one report at a time. The database schema would carry more, but nothing above it
  pretends to.
- **A second format vocabulary.** A firm can change the layout, wording and design of a
  format freely, but the thirteen bracketed tokens are the ones this build fills. A
  fourteenth is a code change.
- **Photographs are not analysed.** Deliberate, and the reasoning is above: asking a model to
  describe a property from a photograph invites exactly the over-claiming this build exists
  to prevent.
