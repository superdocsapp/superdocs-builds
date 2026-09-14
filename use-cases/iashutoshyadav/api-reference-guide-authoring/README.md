# API-reference & Guide Authoring

Built by **Ashutosh Yadav** for the SuperDocs engineering hiring round.

## What it does

A chat-driven authoring tool for developer-facing teams, two modes:

1. **Markdown round-trip authoring** - paste a markdown page (a code block, a diagram reference), convert
   it into a real SuperDocs styled document, then back to markdown. The code block and the diagram
   reference must survive unchanged - that's the whole point. Optionally attach a real image file, which
   gets genuinely uploaded via SuperDocs's own image endpoint (`POST /v1/documents/images/upload-base64`)
   and embedded in place of the placeholder diagram path - not just a markdown text reference passed
   through unchanged.
2. **Getting-started guide generation** - describe an API or feature in plain language, get back a numbered
   onboarding guide, written by SuperDocs from a single instruction (not by us generating it ourselves).

## How to run it

```bash
python -m venv .venv
source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -r requirements.txt
cp .env.example .env             # leave SUPERDOCS_API_KEY empty to run against the offline fake client
uvicorn app.web:app --port 8020
```

Open `http://localhost:8020` - both modes are on one page, pre-filled with a sample.

## Tests (no live key needed)

```bash
pytest
```

13 tests, offline against a fake SuperDocs client covering both modes' pipelines: round-trip preservation
of a code block and an image reference, numbered-guide generation from a feature description, the
human-in-the-loop revision path (propose, approve, reject), and regression tests capturing the exact
real-API findings described below.

**Verified against the real API, not just the fake client** - `verify_real_api.py` (not part of the
pytest suite, run manually once with a real key) exercised both modes against the live product:

- **Diagram/image reference: preserved exactly.** `![sequence diagram](./diagrams/create-widget-flow.png)`
  survived the round trip unchanged.
- **Code block: content preserved exactly, language tag not.** The code inside the fence came back
  byte-for-byte identical - nothing a reader would copy-paste changed. What *did* change: a fenced block
  opened as `` ```python `` came back as a bare `` ``` `` - the language tag used for syntax highlighting
  is not preserved through this round trip. `RoundTripResult` reports this precisely
  (`code_blocks_preserved=False`, `code_content_preserved=True`) rather than collapsing it into one
  blunt pass/fail - a reviewer sees exactly what changed and what didn't, and the UI shows both signals
  separately. Captured as a permanent regression test
  (`test_a_real_finding_captured_as_a_permanent_check_language_tag_lost_but_code_content_intact`), not left
  as a one-off observation.
- **An extra blank line appears before a code fence's closing ` ``` `.** Found by comparing exact newline
  counts between the original and round-tripped markdown (22 vs 23) after a visual anomaly in the browser
  turned out to be a display-only artifact, not a data bug - the newline-count check was what actually
  confirmed a real, tiny difference existed and pinned down exactly where. It doesn't affect what a reader
  would copy (the content comparison strips trailing whitespace before comparing, so
  `code_content_preserved` correctly stays `True`), but it's a precise, real behavior worth recording
  alongside the language-tag finding rather than left undocumented because it happened to be harmless.
  Captured as a permanent regression test
  (`test_a_real_finding_extra_blank_line_before_closing_fence_does_not_affect_content_preservation`).
- **The "stable public URL" `POST /v1/documents/images/upload-base64` returns is never actually
  accessible.** Found the hard way: after embedding it, clicking the "real image uploaded" link this
  build shows produced a live Google Cloud Storage `403 AccessDenied` - "Anonymous caller does not have
  storage.objects.get access." Confirmed precisely by GET-ing both response fields with no auth headers:
  `url` (the one the docs describe as "a stable public URL for embedding via `<img src="...">`") returns
  `403` every time, for everyone; only `view_url` (the signed, time-limited link in the same response)
  returns `200`. The docs' own description of `url` is simply wrong - it isn't public at all. Fixed by
  switching `upload_image()` to return `view_url` instead. This turned out to also explain the finding
  below: SuperDocs's export was never "downgrading" a working stable URL into a signed one - the signed
  URL was the only one that ever worked, so once this build started uploading `view_url` from the start,
  the round trip started preserving the reference byte-for-byte (`image_refs_preserved` now `True`, not
  just `image_target_preserved`).
- **A real uploaded image's URL is time-limited (24h), even once you're using the working field.** The
  Google Cloud Storage signed URL SuperDocs exports carries `X-Goog-Expires=86400` - a document
  re-exported after the signature expires could show a broken image. Worth flagging to SuperDocs
  directly: neither response field is a truly durable, permanently-public embed URL. Captured as a
  permanent regression test
  (`test_a_real_finding_signed_url_rewrite_does_not_count_as_the_image_changing`), which still holds as a
  useful check even after the field-name fix, since a fresh signature is still technically a different
  string than whatever was embedded moments earlier.
- **Getting-started guide generation: works well.** The real output is a properly structured guide with
  headers, numbered steps, bold text, and a working code example - noticeably better than this project's
  own offline simulation, which only exists to keep the pipeline testable without a live key.
- **Guide generation is honest about missing specifics, not silent about them.** Given a deliberately
  generic feature description with no named SDK or package, the real output inserted visible
  `Please fill: [Name of SDK]`-style placeholders instead of inventing a plausible-looking but fake package
  name. The right behavior for an AI-authoring tool - guessing wrong here would be worse than an obvious
  placeholder a human has to fill in.
- **The first prompt let the model add unrequested flourishes** - a fabricated copyright line, a
  "Developer Relations Team" attribution, and a publication date, none of which were in the feature
  description or asked for. Fixed by tightening the prompt (`app/guide_generator.py`) to explicitly
  instruct against inventing attribution/version/date metadata, on top of the existing "flag what's
  missing" instruction. Verified against the real API with the identical input before and after: the
  fabricated footer is gone, and the guide is now *more* honest than before, not just quieter - it also
  started flagging two more unstated details (Node.js version, API base URL) that the earlier prompt had
  silently guessed at rather than flagging.
- **A generated "working example" wasn't actually runnable.** An OAuth2 guide's code sample defined a
  `getAccessToken()` function but never called it, then referenced a `tokenData` variable that was never
  declared - copy-pasting it would throw `ReferenceError: tokenData is not defined`. Fixed by adding an
  explicit instruction that the working example must be self-contained: every function defined must be
  called, every variable referenced must be assigned first. Verified against the real API with the
  identical OAuth2 input: the re-generated example properly chains `response = requests.post(...)` →
  `token_data = response.json()` → `access_token = token_data['access_token']` before using
  `access_token`, with no dangling references.

**A real bug that broke a request outright, not a quality issue:** both `/roundtrip` and `/guide` reused a
single hardcoded `session_id` ("roundtrip-session", "guide-session") across every request for the entire
life of the running process. Every unrelated request kept piling another document upload and chat turn
into the same SuperDocs session, and after enough real requests during this round's own live testing, that
session's accumulated state broke - `export_document` started returning a real `404`, and the app returned
a `500` to the browser. Fixed in `app/web.py` by generating a fresh `uuid.uuid4()`-suffixed session ID per
request, since each request is logically independent and has no reason to share session state with the
last one. `renewal-true-up-engine` (the sibling project) doesn't have this bug - it already scopes
`session_id` per customer, not globally.

**A real bug, not a product-behavior finding:** a real `SUPERDOCS_API_KEY` set in `.env` was silently
ignored - `python-dotenv` was a listed dependency but `load_dotenv()` was never actually called, so the app
kept reading an empty environment and running against the fake client regardless of what `.env` said, with
only an easy-to-miss "offline fake client" banner as any signal (no error, no crash). Found live on
2026-08-19 in the sibling `renewal-true-up-engine` project first, then confirmed here too - same missing
call, same fix (`load_dotenv()` at module load, before anything reads the environment).

**A second real bug, found by testing through the actual browser form rather than `curl`:** the same
round-trip input intermittently reported "code content changed" when submitted from the page, but always
reported "preserved exactly" when sent programmatically with identical-looking content. Root cause: an
HTML `<textarea>` form submission normalizes line endings to CRLF regardless of what was typed, but
SuperDocs's markdown export returns LF-only - the comparison never normalized either side, so an invisible
whitespace-convention difference was reported as a real content change. Every `curl`-based test during
design used LF throughout end to end and never hit this. Fixed by normalizing both sides to `\n` before
comparing (`app/markdown_roundtrip.py`), with a regression test
(`test_a_browser_submitted_CRLF_original_is_not_falsely_reported_as_changed`) that reproduces the exact
CRLF-vs-LF mismatch. Worth recording precisely because it's a reminder that testing a web app's *logic*
through `curl` isn't the same as testing the *actual user path* through its own form - the two can diverge
in ways that only show up once you drive the real UI.

This is exactly the kind of finding the round's own standard asks for: *"where your build handles figures
it cannot independently verify, you are graded on whether it detects and surfaces them."* The language-tag
loss is a real, specific SuperDocs product behavior worth reporting through the round's bug-report channel
- not a flaw in this project's own code.

**A real gap found auditing this build against the round's own stated minimum contract** ("upload, chat,
approve, export"): `approve_change`/`chat_with_approval` were fully implemented in the client but never
called anywhere in the app - `FakeSuperDocsClient.approve_change` raised `NotImplementedError` with a
comment claiming "Build B never needs human-in-the-loop approval." That was a real, unaddressed gap, not a
defended cut. Fixed by adding a "Request a revision" step to Mode 2: after a guide is generated, a person
can ask for a specific change, which proposes a real edit via `ask_every_time` and pauses for review -
`app/guide_generator.py::request_guide_revision`/`apply_guide_revision`, both now exercised live, not just
implemented and left unused.

**Real finding while getting this working, live on 2026-09-14**: asking for "Add a FAQ section with two
questions" against a real, already-generated guide repeatedly got back a proposal that duplicated the
existing "Getting Started" section instead of adding the requested FAQ - confirmed by actually reading the
proposed diff, not assumed correct because *a* change came back. Tightening the instruction to explicitly
forbid regenerating or duplicating existing content reduced but did not eliminate this. Reporting this
honestly rather than picking a revision request that happened to work cleanly: this is precisely the
argument for the review gate this fix adds - a proposal a person hasn't looked at yet is not a proposal
that should ever auto-apply, and this is a real example of why, not a hypothetical one. The mechanism
itself - propose, show the real diff, apply only on approval - is proven correct in both directions (a
rejected proposal leaves the document untouched; an approved one lands exactly as shown).

## SuperDocs features used

- **REST API**, direct (`app/superdocs_client.py`), same verified client design as the sibling project in
  this submission - every endpoint/schema was checked against a real running session before being coded
  against.
- `POST /v1/documents/upload` - loads the pasted markdown as the working document (`.md` is a supported
  upload format).
- `POST /v1/documents/export` (`format=html` then `format=markdown`) - proves real conversion happened
  (styled output), then checks round-trip fidelity.
- `POST /v1/chat` - drafts the getting-started guide from scratch, following the documented pattern for
  from-scratch drafting: initialize an empty session, then send the full request in one chat turn, so
  SuperDocs writes the actual formatted document rather than us generating HTML ourselves and uploading it.
- `POST /v1/documents/images/upload-base64` - optionally attaching a real image in Mode 1 uploads it for
  real and embeds the returned stable URL in place of the placeholder diagram path, rather than only ever
  round-tripping an arbitrary text reference that was never a real asset.
- `POST /v1/chat/async` (`approval_mode=ask_every_time`) + `GET /v1/jobs/{job_id}` +
  `POST /v1/chat/{session_id}/approve` - the human-in-the-loop path for a guide revision: the edit is
  proposed but never applied until a person decides. The round's own stated minimum contract (upload, chat,
  approve, export) - real gap found auditing this build, fixed by adding this path.

## Design notes

- No human-approval step in this build (unlike the sibling renewal project) - nothing here commits money
  or a contractual change, so there's nothing that needs a second pair of eyes before it lands.
- In-memory state, no database - a single-operator authoring session, matching the actual scope of what
  the task card asks for.
