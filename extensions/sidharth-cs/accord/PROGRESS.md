# Progress and assumptions log

Same convention as Task 1's `PROGRESS.md`: assumptions logged as they're made,
with reasoning, so the next session doesn't have to reverse-engineer a
decision from the code.

---

## Milestone 0 — RTMS viability spike

**Goal:** find out whether `meeting.rtms_started` fires on this Zoom account
at all, before any drafting logic depends on the answer. Nothing here drafts
a document; it only proves or disproves the transcript channel.

**A1 — CDN script tag, not the npm/Vite pipeline.** `panel.html` loads
`@zoom/appssdk` via `<script src="https://appssdk.zoom.us/sdk.js">`, sourced
from the SDK's own README, rather than pulling in the real frontend's
Vite/React toolchain early. Milestone 2 is where the real panel gets built;
this page exists only to click one button and prove a webhook fires. Keeping
it framework-free keeps M0 isolated from M2, per the plan's own milestone
table.

**A2 — No `__init__.py` files.** Matches Task 1's `app/` — implicit namespace
packages, one less boilerplate file per directory.

**A3 — No persistence, no CLI, no docker-compose.** Per the simplicity
directive locked into the plan (decision 3): none of these materially improve
a webhook-logging spike. Added if a milestone actually needs them, not before.

**A4 — `version: '0.16'` in `zoomSdk.config()`.** Taken directly from the
`@zoom/appssdk` README's own usage example, corroborated by the currently
published package being `0.16.x`. Not guessed.

**A5 — Requesting `startRTMS`/`pauseRTMS`/`resumeRTMS`/`getRTMSStatus` as
capabilities before they're granted in the Marketplace app config.** This is
deliberate, not an oversight: `getSupportedJsApis()` is called right after
`config()` specifically to check whether the Marketplace side has caught up,
and the panel reports "not supported yet" rather than assuming it worked —
see `panel.html`. The actual grant happens in the Zoom Marketplace UI, which
only the account holder can do; this repo can't do it.

**Done, via the Marketplace UI (not this repo's code) — see the dated log
below for the session each happened in:**
- RTMS scopes and capabilities added. **Correction to A5's guess above:**
  the scopes Zoom actually auto-grants when the two RTMS webhook events are
  added are `rtms:read:rtms_started` and `rtms:read:rtms_stopped` — confirmed
  by downloading and reading the app's own manifest JSON, not assumed.
  `meeting:read:meeting_audio`/`meeting:read:meeting_transcript` (named in an
  earlier draft of this note, sourced from general Zoom docs before the real
  manifest was checked) do not appear anywhere in this app's actual
  configuration.
- Cloudflare Tunnel installed (`brew install cloudflared`) and running as a
  quick tunnel (`cloudflared tunnel --url http://localhost:8010`, no account
  needed). Current URL: `https://firms-giant-sept-commissions.trycloudflare.com`
  — ephemeral, changes if the tunnel restarts; whoever picks this up next
  should expect to regenerate it and re-paste it into Home URL / webhook URL
  / OAuth fields below.
- Home URL and webhook Event Subscription URL both set to the tunnel URL.
  `ZOOM_WEBHOOK_SECRET_TOKEN` set in `.env` (by the account holder, not
  pasted by the agent — see the repo's own key-handling discipline).

**Still outstanding — needs the account holder physically:**
- Click "Add app now" on the Local Test page (see the dated log entry below
  for why this was blocked and how it was unblocked).
- Open a real Zoom meeting, load the panel, click "Start RTMS Test", and
  watch the backend's terminal for `meeting.rtms_started` within about 20
  seconds.

**Verified from this session, without needing the live account:**
- `make setup && make test` — 4/4 pass: the `endpoint.url_validation`
  handshake produces the documented `encryptedToken`, a correctly-signed
  event is accepted, a missing signature is rejected, and a tampered body
  (valid signature, different bytes) is rejected. One benign
  `StarletteDeprecationWarning` about `httpx`/`starlette.testclient` appears
  on this machine's dependency versions — noted, not chased; it doesn't
  affect correctness and isn't this repo's code.
- The server boots and, over real HTTP (not just the test client), `GET
  /health` and `GET /` both return 200, and `POST /webhooks/zoom` round-trips
  the `endpoint.url_validation` handshake and correctly 401s an unsigned
  event — the same behavior the unit tests assert, confirmed again through
  the actual HTTP stack.
- **Port 8010, not 8000.** Task 1's own `web` service already documents
  `localhost:8000` as its interface; something was listening on 8000 in this
  environment when this was tested. Since nothing in this milestone's design
  depends on a specific port (Home URL/redirect URL aren't configured yet —
  see "still outstanding" above), moved to 8010 rather than investigating or
  touching whatever else owns 8000. `Makefile`, `.claude/launch.json` (both
  copies — see below) all agree on 8010.
- **Note on this session's tooling:** the Browser-preview MCP tool
  (`preview_start`) couldn't launch the app directly — its sandboxed child
  process got `PermissionError` reading `zoom-app/.venv/pyvenv.cfg`, because
  this repo lives outside the session's primary working directory
  (`~/Desktop/gethired`) and that tool's sandbox appears scoped to it. A
  `zoom-app` entry was still added to both `~/Desktop/gethired/.claude/launch.json`
  (what the tool actually reads in this environment) and this repo's own
  `.claude/launch.json` (correct once this moves/is worked on from its own
  root), for whenever that constraint doesn't apply. Verification for this
  session used a background `uvicorn` process plus `curl` instead — real
  HTTP, just not through that particular tool.

---

### Investigation — "Live Deliverable" not appearing in the Zoom desktop client

**Symptom:** with the webhook receiver, Home URL, Event Subscription, RTMS
scopes and RTMS SDK capabilities all confirmed correctly configured (per the
downloaded manifest), the app still did not show up under Apps inside a real
Zoom meeting, so `startRTMS()` could never be called.

**Investigation, not a code change.** Per Zoom's own current docs
([Local Test](https://developers.zoom.us/docs/build-flow/local-test/)), a
development app only becomes visible/loadable in the client after an
explicit **"Add app now"** action on the Marketplace's **Local Test** page —
this is a distinct top-bar entry (`Local Test ▾` next to Manifest File /
Preview), not something under Basic Information or Features, and easy to
miss. Opening it showed the direct, first-party answer:

- The `Local Test ▾` menu's two actions — "Copy authorization URL to share"
  and "Add app now" — were both **greyed out**.
- The left-nav badge next to **Local Test** read **"Not ready"**.
- The Local Test page itself stated plainly: *"The following fields are
  required to add and share your app. Basic Information (2)."*
- Expanding that pointed at **Basic Information → OAuth Information**, where
  both **OAuth Redirect URL** and **OAuth Allow Lists** showed inline
  `This field cannot be empty` errors.

**Root cause:** the app's OAuth Redirect URL and OAuth Allow List were never
filled in. This is not new information — `PROGRESS.md`'s very first RTMS
entry (this session, above) already named "Home URL and redirect URL" as
outstanding and explicitly deferred the redirect URL "until an HTTPS tunnel
exists." The tunnel now exists; the redirect URL was simply never revisited
after that. Nothing about RTMS, account eligibility, Zoom client version, the
webhook config, or App Credentials was the actual blocker — all of those
were already correct, confirmed via the manifest before this investigation
started.

**Fix applied (Marketplace configuration only — no backend or frontend code
touched):** both fields were set to the tunnel's root URL,
`https://firms-giant-sept-commissions.trycloudflare.com`. This is a
placeholder, stated plainly: no `/auth` callback route exists in
`backend/app/` yet (in-client OAuth is out of M0's scope per the plan —
`zoomSdk.config()` in `panel.js` doesn't request `authorize`-related
capabilities). Pointing the redirect at the Home URL means it resolves to a
real 200 instead of a 404 if Zoom's "Add app" flow touches it, without
writing any OAuth code that a later milestone would just have to redo. This
needs a real `/auth` endpoint once the plan's §20 authentication flow is
actually implemented (M4 territory) — flagged here so it isn't mistaken for
finished OAuth support.

**Result, confirmed live on the Marketplace UI immediately after saving:**
the "App created" sidebar status changed to **"Ready for local test,"** the
Local Test badge changed from "Not ready" to **"Local only,"** and **"Add app
now" is now an active (not greyed out) button.** Screenshotted at each step.
Clicking it is the account holder's action, not this session's — matches the
repo's own "human holds anything that authorizes/installs" posture, echoed
from Task 1's gate philosophy.

**Add app now / Allow was clicked (account holder) and the panel loaded for
real inside a meeting** — `config() ok, runningContext = "inMeeting"`. First
confirmed evidence the app installs and launches correctly.

---

### `getSupportedJsApis()` reported `startRTMS` missing — two real causes found, neither was RTMS entitlement

The panel's own pre-flight check (`panel.js`) reported *"startRTMS is not in
getSupportedJsApis()."* Told not to guess which of {genuine account
entitlement, truncated log} was true. Rather than trust a copy/paste out of
Zoom's embedded webview (unreliable — the first attempt came back visibly
garbled), added a **diagnostic-only** route, `POST /debug/log` in `main.py`,
and had `panel.js` relay the raw `getSupportedJsApis()` result to it directly
— so the exact value could be read from our own terminal instead of a screen
copy. This route is not part of M0's design; remove once RTMS status is
settled.

**Before that could produce a second data point, the panel stopped loading
at all** — Zoom's client showed its own generic error (*"Something went
wrong," code `56059C40-0x02-0212-0000-0B-0A-07"*). Investigated rather than
assumed:

- `ps` showed the `cloudflared` process still running, but its own log
  (`/tmp/zoom-app-tunnel.log`) had been repeating *"control stream
  encountered a failure while serving"* / *"Retrying connection in up to
  1m4s"* on a loop since 01:07 UTC. `curl` against the tunnel URL returned
  530, then `000` (fully unreachable) minutes later.
- **Root cause: the free Cloudflare quick tunnel died.** Documented,
  expected behavior for accountless quick tunnels ("no uptime guarantee" —
  cloudflared prints this at startup; also flagged as a real risk in this
  file's own earlier session). Not a Zoom-side issue, not a code issue.
- **Fix:** killed and restarted `cloudflared`. Quick tunnels mint a new
  hostname every start — old one
  (`firms-giant-sept-commissions.trycloudflare.com`) is dead, current one is
  **`https://andrews-great-aruba-massive.trycloudflare.com`**. Updated in all
  four places that had the old URL: Home URL, the `M0 RTMS spike` webhook
  endpoint, OAuth Redirect URL, OAuth Allow Lists — confirmed by
  re-downloading the manifest and reading back all four fields, not by
  trusting the form UI. "Ready for local test" held throughout; re-adding the
  app was not required, only re-pointing the URLs.

**While re-validating the new Home URL, found a second, real, separate bug**
— this one actually in this repo's code: `curl -I` (HEAD) against `/`
returned `405 Method Not Allowed` while `GET /` returned `200`. Zoom's own
Home-URL-reachability checker almost certainly uses HEAD (lightweight
liveness probe, common practice); our route only handled GET, so Zoom
reported "Home URL is unreachable" even though the page was genuinely up and
serving correctly for real browser navigation. **Fixed:** `main.py`'s `/`
and `/health` routes changed from `@app.get(...)` to
`@app.api_route(..., methods=["GET", "HEAD"])`. Confirmed both methods
return 200 locally and through the tunnel post-fix; `make test` still 4/4.

**Settled — `startRTMS` was present the whole time; the panel's own check was
wrong.** The `/debug/log` relay produced the real, complete array:

```
["getSupportedJsApis","getRunningContext","getMeetingContext","getUserContext",
 "getMeetingUUID","startRTMS","stopRTMS","getRTMSStatus","pauseRTMS","resumeRTMS"]
```

All 10 requested capabilities, `startRTMS` included. **Not an RTMS
entitlement, account, client-version, or Marketplace-configuration issue —**
every one of those was already correct. The bug was in `panel.js`: the SDK's
response object carries the array under the key **`supportedApis`**, but the
code read `supported.supportedJsApis` (with an extra "Js", presumably
misremembered from the method name `getSupportedJsApis()` itself). That's
`undefined` on the real object; `(undefined || [])` silently becomes `[]`;
`[].includes('startRTMS')` is always `false`. The check couldn't have passed
regardless of what Zoom actually granted — a false negative in our own code,
not a signal about the platform.

**Fixed:** both reads in `panel.js` changed to `supported.supportedApis`.
Static file, no server restart needed — confirmed the corrected file is what
the tunnel actually serves before telling the account holder to retest.

**This is why the raw-relay diagnostic mattered.** The on-screen log used
the same (wrong) `supported.supportedJsApis` value for its own display, so a
clean copy/paste from the panel would *also* have shown an empty array and
looked like confirmation of the wrong conclusion. Only bypassing our own
logging code — via the JSON-serialized version of `supported` sent to
`/debug/log` before anything touched the buggy field name — surfaced the
real data.

---

## Milestone 0 — verdict: RTMS fails at the platform level, not ours

With the field-name bug fixed, the panel correctly reported Ready and
enabled Start. The account holder clicked **Start RTMS Test** for real, in a
live meeting, with every prerequisite on our side confirmed correct.

**What happened:**
- `startRTMS()` resolved client-side: `{"message":"Success"}`.
- Zoom's own client simultaneously surfaced a native toast: **"Your app
  failed to access meeting content."**
- The backend log — actively monitored — shows no `meeting.rtms_started`
  (or `meeting.rtms_stopped`) at any point. Waited 30+ seconds past the
  design's own 20s bounded-wait threshold (§14 of the plan) before
  concluding absence, not assuming it from a single snapshot.

**This matches a specific, pre-existing, documented report**, found during
this project's original Zoom/RTMS research (before any implementation
started): a Zoom developer-forum thread titled *"zoomSdk.startRTMS()
resolves successfully but client shows 'failed to access meeting content'
and no meeting.rtms_started webhook fires"* — same symptom, same shape,
reported by someone else against the same platform, unresolved at the time
it was found. Not a coincidence being stretched to fit; the title is
essentially a direct description of what happened here.

**Everything on this repo's side of the boundary is confirmed correct**
before reaching this point — each verified independently, not assumed:
Marketplace scopes (`rtms:read:rtms_started`/`rtms:read:rtms_stopped`), all
10 Zoom App SDK capabilities including the 5 RTMS methods, the webhook
Event Subscription and its signature verification, Home URL (including the
HEAD-vs-GET bug), OAuth Redirect URL/Allow List, and the `panel.js`
field-name bug. Ruling all of those in as correct is exactly what makes this
result readable as a platform/account-side RTMS limitation rather than one
more configuration gap — the kind of limitation the plan's top-listed
technical risk (§30.1) named as the reason `TranscriptProvider` exists as an
abstraction in the first place, before a single line of M1 was written.

**Per the plan's own pre-declared contingency (§14, §30.1, §31 M0/M3/M4)
and this session's explicit instruction:** this is read as "RTMS fails
because of account limitations," not a bug to keep chasing. Architecture is
unchanged — nothing here calls for a redesign, only for M4 (the
`RTMSTranscriptProvider` wiring) to be built expecting this account may
never pass, and for `ManualTranscriptProvider` to be the real v1 default
rather than a fallback that's assumed unlikely.

**Not ruled out, stated plainly:** this could still be resolved by "Developer
Pack credits" (named in Zoom's own RTMS prerequisites, never obtained this
session) or by Zoom fixing the platform-side bug the forum thread reports.
Neither is something this repo can act on. If either happens later, M4
becomes a real milestone to build instead of a skipped one — the
architecture doesn't need to change either way, only which
`TranscriptProvider` is active.

**Milestone 0: complete.** The question it existed to answer — does RTMS
work on this account, checked for real rather than assumed — has a definite
answer, obtained honestly, with every one of this repo's own moving parts
ruled out first. Proceeding to M1 per the milestone table, building against
`ManualTranscriptProvider` as designed for exactly this outcome.

**Recorded status: RTMS is currently unavailable in this validated
development environment** — not removed from the architecture, not
redesigned around. `TranscriptProvider` stays exactly as designed;
`RTMSTranscriptProvider` remains a real, production-capable implementation
to enable the moment the platform (or Developer Pack credits) makes it work;
`ManualTranscriptProvider` is simply which one is *active* for development
right now, a runtime fact, not an architectural one.

---

## Milestone 1 — Backend skeleton + SuperDocs client

**Goal, per the plan's own milestone table:** prove the 4-call contract
(upload, chat, approve, export) still behaves as documented, from this
codebase's own client — isolated from Zoom entirely, no meeting needed.

**Scope decision, stated plainly:** `superdocs/client.py` implements exactly
what M1 needs — upload, chat (async only, never the sync `/v1/chat` per the
plan's own "decisive simplification"), job polling, approve, export.
Session lifecycle (`/v1/sessions/init` etc.), `continue_prompt` handling,
and signed download URLs are all real, documented endpoints (Appendix A)
this client will need — but not until M3's drafting engine actually calls
them. Building them now against a guess at how they'll be used would be
exactly the kind of speculative completeness the simplicity directive rules
out; the endpoints are documented precisely enough to add when a real
caller exists.

**A7 — Response schemas allow extra fields; `status` is `str`, not a closed
`Literal`.** SuperDocs is a third-party API this repo doesn't control.
`extra="allow"` plus an open status type means a field or status value this
client hasn't seen yet surfaces to the caller instead of crashing the whole
poll loop — directly answers "SuperDocs API contract changes" in the plan's
own Technical Trade-offs (#3) rather than leaving it as a paper risk.
Locked in by a test: `test_get_job_tolerates_a_status_value_this_client_has_never_seen`.

**A8 — No retry/backoff in `client.py`.** Bounded retry is Milestone 6
(Hardening) scope per the plan's §23, applied to *how the drafting engine
uses* the client — putting retry logic inside the client itself now would
mean redoing it once M3 defines what "bounded" actually means for a live
meeting (batch coalescing, the single-in-flight-call guard, etc.). A failed
call raises `httpx.HTTPStatusError`; locked in by
`test_a_4xx_response_raises_rather_than_being_swallowed`.

**Testing, same split Task 1 uses:** `tests/test_superdocs_client.py` — 7
tests against `httpx.MockTransport`, no network, no API key, request
shaping and response parsing only. `scripts/smoke_superdocs_contract.py` is
the one thing in this repo that's allowed to need a real
`SUPERDOCS_API_KEY` and hit the real network — mirrors the *pattern*
Task 1's own `scripts/probe_superdocs_api.py` established (small structured
document, named sections, verify they survive an edit) using this
codebase's own client instead of raw `httpx` calls, and without importing
across the Task 1/Task 2 boundary. Not yet run against the real API this
session — needs `SUPERDOCS_API_KEY`, which the account holder adds to `.env`
themselves, same discipline as the webhook secret.

**Verified this session:** `make test` — 11/11 pass (4 from M0's webhook
tests, 7 new). Server still boots cleanly with the two new config fields
(`superdocs_api_key`, `superdocs_base_url`) — no startup warning added for a
missing `SUPERDOCS_API_KEY`, since unlike the webhook secret, nothing at
server-boot time needs it yet; only `make smoke` does.

---

### `make smoke` against the real API — 3 of 4 calls proven, 1 unresolved

Account holder added `SUPERDOCS_API_KEY` to `.env`. First real run failed
immediately with a config bug (below), then surfaced two genuine SuperDocs
contract mismatches on top of the one already known, then hit a fourth issue
that's still open. Each is a separate, real finding — recorded in order.

**Config bug (this repo's, fixed):** `Settings.model_config`'s `env_file=".env"`
is relative to the process's *working directory*, and `make smoke`/`make
dev`/`make test` all `cd backend` first — so it was resolving to the
nonexistent `backend/.env` instead of `zoom-app/.env`. Silent until now
because every other path either set env vars directly (the webhook tests)
or happened to be launched with `zoom-app/` as cwd manually. **Fixed:**
`config.py` now anchors `env_file` to an absolute path,
`Path(__file__).resolve().parents[3] / ".env"`, independent of cwd or entry
point.

**Contract mismatch #2 (SuperDocs', confirmed): upload's field is
`file_base64`, not `document_base64`.** The live API's own 422 named it
exactly: `{"type":"missing","loc":["body","file_base64"],"msg":"Field
required"}`. Notably, this is now the *second* different name for the same
concept across three sources — the docs said `document_base64`, Task 1's own
independently-written probe script guessed `document_html`, and the live
server wants `file_base64`. None of the three agree. Fixed in `client.py`,
locked in by a test.

**Contract mismatch #3 (SuperDocs', confirmed): `metadata.pending_changes`
is `null`, not `[]`, when nothing changed yet.** A plain `list[...]` field
rejects `null` outright. Fixed with a `field_validator(mode="before")`
coercing `None → []` on both `pending_changes` and `chunk_diffs` (the second
extrapolated from the first — same API, same pattern, not separately
observed yet, stated plainly). Locked in by a test.

**Contract mismatch #4 (SuperDocs', confirmed): approve's real required
body is `{job_id, approved}`, not the docs' `{changes: [...]}` batch
array or `{approved, feedback}` single-change shape.** The 422 named
`job_id` and `approved` as the two missing fields; `changes` wasn't flagged
as unexpected, just silently ignored. Fixed in `client.py`.

**Open, unresolved — approve's HTTP shape is now valid, but nothing it
does actually applies the edit.** With the 422 gone, every real call
(with or without an explicit `chunk_id` alongside `job_id`/`approved`)
returns `{"status": "ok", "message": "Approval processed",
"batch_complete": false}` — but re-polling the job immediately afterward
shows it still `status: awaiting_approval` with the exact same pending
change unresolved, and the subsequent export still contains the
*original*, pre-edit document. Tried twice: once sending only
`{job_id, approved}`, once adding `chunk_id` from the pending change — both
produced byte-identical responses and the same lack of effect.
`awaiting_kind` is `null` throughout (rules out a missed
`continue_prompt` step). Re-fetched the docs specifically for this
endpoint afterward: they describe `approved`/`feedback`/`changes` as the
request shape and say nothing about `job_id` at all — directly contradicting
what the live 422 itself required — and don't mention `batch_complete` as a
response field anywhere. Docs and live behavior disagree with each other on
this endpoint, not just with what was originally read.

**Stopped here rather than continuing to guess.** Each additional live
attempt spends a real, metered SuperDocs operation from the account
holder's quota for a diminishing chance of a lucky guess — exactly the
point on this project's own "verify at implementation time, don't invent"
principle where continued invention should hand back to a person rather
than keep spending someone else's resource on trial and error.

**Where this leaves M1:** upload, chat, and export are fully proven against
the real API — real HTTP calls, real responses, correct content survival,
correct edit application confirmed by content (not just section-name
survival). Approve is HTTP-contract-valid (no more 422s) but its actual
effect is unconfirmed and, on the evidence gathered, looks like it may not
be applying at all through this exact call shape. This is a real gap in
"the 4-call contract... behaves as documented" — three-quarters proven
honestly beats four-quarters claimed without checking.

---

## Milestone 1 — final status: complete, with one documented limitation

- **Upload** — validated against the live SuperDocs API.
- **Chat/Edit** — validated against the live SuperDocs API.
- **Export** — validated against the live SuperDocs API, including that the
  requested edit's content actually landed (not just section survival).
- **Approve** — partially validated:
  - Request validation errors were resolved (the real required shape,
    `{job_id, approved}`, was found and matches what the server's own 422
    demanded).
  - The documented request shape does not match the live API's real one —
    confirmed independently on this endpoint specifically, not inferred
    from the upload mismatch alone.
  - The live API accepts the revised request (200, no validation error) but
    does not advance the document to an approved state — the job stays
    `awaiting_approval`, `batch_complete` stays `false`, and export
    continues to return the pre-edit document.
  - Further investigation would require additional metered API operations
    against a real account, with no remaining hypothesis to test — stopped
    here rather than keep guessing at the account holder's expense.

**Not changed:** `superdocs/client.py`'s public shape (`upload_base64`,
`chat_async`, `get_job`, `approve`, `export`) — the abstraction stands;
`approve`'s known limitation lives inside it, not around it. **Marked as a
known integration issue, to revisit with fresh eyes (and SuperDocs' own
input, if sought) when M3 or M5 actually needs a working end-to-end approval
path** — not before, since nothing between here and there depends on it
working.

Proceeding to Milestone 2 exactly as planned: the Vite/React panel shell,
isolated from any drafting logic, no dependency on approve or anything else
M1 touched.

---

## Milestone 2 — Vite/React panel shell

**Goal, per the plan's milestone table:** the panel loads and reads real
meeting context in a real Zoom meeting, using only the 5 already-enabled
APIs — isolated from any drafting logic.

**Built:** `frontend/` — React 18 + Vite, matching Task 1's `ui/` tooling
exactly (same dependency versions, same no-router/no-state-library
minimalism per the plan's §11). `zoom/sdk.js` is the one module that imports
`@zoom/appssdk` — every other file goes through it, same isolation reasoning
as the backend's `TranscriptProvider`. Requests only `getSupportedJsApis`,
`getRunningContext`, `getMeetingContext`, `getUserContext`, `getMeetingUUID`
— the RTMS capabilities from M0's spike are deliberately not requested here;
nothing in this milestone has RTMS logic, and requesting an unused
capability is exactly what PROGRESS.md's own least-privilege note (A5)
argues against. `App.jsx` renders connecting/connected/error and, once
connected, the running context and meeting UUID — the whole of M2's proof
target, nothing more (no Setup/LiveDraft/Review/Export screens — those
belong to M3 and M5, and have nothing to render yet).

**Verified this session:**
- `npm install` — 66 packages, 0 vulnerabilities.
- `npm run build` — compiles cleanly, 29 modules, no errors.
- `npm run dev` + the Browser preview tool (worked this time — M0's note
  about the sandboxed Python venv permission wall was specific to reading
  `pyvenv.cfg`, not general to this environment; a plain Node process hit no
  such wall): page renders "Live Deliverable", and — opened as a plain
  browser tab, not inside Zoom — shows *"Not connected — The Zoom Apps SDK
  is not supported by this browser"*. This is the correct, expected failure
  mode, not a bug: it's the exact same message M0's CDN-script panel showed
  under the same condition, now reproduced through the real npm/Vite
  toolchain instead. No console errors beyond normal Vite dev noise.

**Not yet done — genuinely needs a live meeting, same as M0:** confirming
the panel actually connects and reads context *inside* Zoom. Doing that
means pointing the Marketplace Home URL at this frontend (built and served
by FastAPI, or the Vite dev server through a fresh tunnel) instead of M0's
static `panel.html`.

**Resolved the same session, the clean way — no Marketplace change
needed.** `main.py` now serves `frontend/dist` (built via `npm run build`)
at `/`, mounted at `/assets` for the JS/CSS bundle so it can't shadow
`/health` or `/webhooks/zoom`. Same Home URL, same tunnel, already
registered — Zoom just needs the panel reloaded, not re-added. Verified
before calling it done, not assumed:
- `GET /` and `HEAD /` both 200, locally and through the existing tunnel.
- The built JS bundle (`/assets/index-*.js`) loads with a 200, both paths.
- Opened via the Browser tool at `http://localhost:8010/`: zero console
  errors, including no CSP violations — worth checking specifically,
  because this also **tightened `Content-Security-Policy`'s `script-src`
  from `'self' https://appssdk.zoom.us` down to `'self'` alone**. M0's
  spike loaded `@zoom/appssdk` from Zoom's CDN via a `<script>` tag, hence
  that allowance; M2's panel imports it as an npm dependency, so Vite
  bundles it directly into the built JS — nothing external left to allow.
  `make test` still 12/12 after the change.
- Renders the same honest *"Not connected — The Zoom Apps SDK is not
  supported by this browser"* message opened outside Zoom, matching M0's
  own proven-correct behavior for the same condition, now confirmed through
  the real build-and-serve path rather than only the Vite dev server.

M0's static spike page is untouched at `/static/panel.html` — not deleted,
just no longer what `/` serves.

**Still needs the account holder:** reload the panel inside a real meeting
(close and reopen from Apps — same Home URL, nothing to reconfigure) to
confirm it connects for real. That's the one thing that was never going to
be provable from outside Zoom's client, same as M0.

**Confirmed live, same session.** Reloaded in a real meeting: **Connected**,
running context `inMeeting`, a real meeting UUID displayed. `zoomSdk.config()`
and the three context calls (`getMeetingContext`, `getUserContext`,
`getMeetingUUID`) all resolved correctly through the real npm/Vite build
served by FastAPI — not just the CDN-script path M0 proved.

**Milestone 2: complete.** Every claim in its proof target is now backed by
a live meeting, not just a build log: panel loads, connects, reads real
context. Ready for Milestone 3.

---

## Milestone 3 — Draft Engine / live drafting workflow (manual-entry only)

**Goal, per the plan's milestone table:** first end-to-end vertical slice —
Setup → session init → `ManualTranscriptProvider` → batcher/classifier → one
chat call → integrity check → panel update — proving the drafting engine is
correct independent of M0's RTMS outcome. RTMS itself stays untouched;
`RTMSTranscriptProvider` doesn't exist yet, by design (M4, conditional on M0).

**Built, backend:**
- `transcript/provider.py` — the `TranscriptEvent` shape and `TranscriptProvider`
  Protocol (`name`, `start`, `stop`, `status`, `events`), the abstraction
  everything downstream depends on.
- `transcript/manual_provider.py` — `ManualTranscriptProvider`. `submit()` is
  deliberately *not* part of the Protocol — it's provider-specific ingestion,
  the same way a future RTMS provider would have its own websocket consumer.
  This split is what makes "RTMSProvider could replace ManualTranscriptProvider
  without changing Draft Engine code" true by construction: `session.py`'s
  consumer loop only ever calls `start`/`events` on the typed `TranscriptProvider`,
  never anything Manual-specific.
- `drafting/classifier.py` — two-signal correction detection (cue phrase +
  value/entity overlap with the current draft; both required, otherwise
  defaults to addition — same asymmetry the design doc specifies, favoring
  information preservation over classification precision).
- `drafting/batcher.py` — silence-gap / size-ceiling / max-wait / correction-cue
  flush triggers, any one fires.
- `superdocs/integrity.py` — the two-signal structural-integrity checker
  (diff proportionality + independent heading-count/text-length scan),
  flags if either fires.
- `drafting/session.py` — `MeetingSession`, the Draft Engine orchestrator:
  consumes the provider, batches, classifies, calls SuperDocs, integrity-checks,
  publishes state to subscribers. In-memory session registry, one per meeting
  UUID, matching the M0 no-persistence decision.
- `api/routes_session.py` + `api/routes_events.py` — `POST/GET
  /api/meetings/{uuid}/transcript`, `GET /state`, `GET /events` (SSE). Both
  REST routes lazily create the session via the same `get_or_create_session`
  — idempotent, so there's no separate init step for manual entry.

**Built, frontend:** `hooks/useMeetingSession.js` (one hook, not the plan's
two — `useMeetingSession` + `useLiveEvents` split into separate files reads
as unnecessary indirection for a single-panel, single-state-shape app; see
"deliberate simplifications" below) fetches initial state, subscribes to the
SSE stream, folds events into state, exposes `submitTranscript`. `App.jsx`
extended (not replaced) with the manual-entry textarea + Send button,
transcript history, job-status pill, activity log, and a read-only draft
preview (`dangerouslySetInnerHTML` of SuperDocs' own returned HTML — no
editor, per the non-negotiable "the panel orchestrates, SuperDocs edits"
rule). State only ever moves forward from the SSE stream, never optimistic
local mutation, matching §11.

**Deliberate simplifications, stated plainly:**
- The single-in-flight-call-per-session guard (`asyncio.Lock` in
  `_handle_batch`) *serializes* overlapping batches rather than truly
  coalescing them into one merged call. Simpler; acceptable for M3.
- `useMeetingSession`/`useLiveEvents` collapsed into one hook file (above).
- No Setup/Review/Export screens — M3 is one continuous view; those are M5.

**Two real bugs found and fixed — both invisible to the unit test suite,
both only surfaced by live verification against the real SuperDocs API:**

1. **`Batcher._flush` self-cancellation.** On a timer-fired flush (silence-gap
   or max-wait), `_flush()` ran *as* `_silence_task`/`_maxwait_task` but
   unconditionally cancelled both — including whichever one was currently
   executing it. `task.cancel()` on the running task schedules a
   `CancelledError` for its next `await`; since `_handle_batch`'s `except
   Exception` doesn't catch `CancelledError` (a `BaseException` subclass,
   not `Exception`), the batch died silently mid-`httpx` call with no error
   ever surfaced — `job_status` just froze on `sending` forever. Every
   mocked test passed because the fakes (`_Recorder`, `FakeSuperDocsClient`)
   had no genuine internal `await` suspension point for the pending
   cancellation to interrupt — only real network I/O gave the event loop
   that opportunity. **Fix:** `_flush()` now skips `asyncio.current_task()`
   when cancelling. **Test suite strengthened accordingly** — both fakes now
   `await asyncio.sleep(0)` before returning, a real suspension point.
   Reverted the fix temporarily to confirm the strengthened fakes actually
   catch the regression (7 tests failed, as expected) before reapplying it.
2. **`JobStatusResponse` schema didn't match the live wire shape.** Built
   from the documented/assumed shape (`document_changes` top-level on the
   job object, `document_changes.chunk_diffs[]` with `html_before`/
   `html_after`). The real API — confirmed via a raw, unparsed
   `GET /v1/jobs/{job_id}` response under `approval_mode=auto` — nests
   everything under `result`: `result.document_changes.changes[]`
   (`chunk_diffs` was present in the schema but observed `null` on every
   live job tested), with fields `old_html`/`new_html` and, for an addition,
   `operation: "create"` (confirmed live). `"delete"`/`"update"` are
   inferred from that same CRUD-style naming, not independently confirmed —
   noted directly in `integrity.py` where it matters; if wrong, that specific
   check just never fires, and Signal B (the independent structural scan) is
   the backstop that doesn't depend on SuperDocs' operation labels at all.
   **Fix:** added `JobResult`, changed `JobStatusResponse.document_changes`
   to a property reading `result.document_changes`, renamed
   `DocumentChanges.chunk_diffs` → `changes`. Same class of finding as M1's
   `file_base64` mismatch — the live response is the authority, not the docs
   page or the original guess.

Both bugs together meant the draft never actually updated before this
session's fixes, despite the job reporting `completed` — worth stating
plainly since it's exactly the kind of silent failure this project's own
integrity checker exists to catch on the *content* side; this was the same
failure mode one layer down, in the plumbing that feeds the checker.

**Verified live this session, real SuperDocs API, real account:**
- Addition path: submitted transcript text via `curl` against the real
  running server → batch flushed → `upload_base64` (lazy doc init) →
  `chat_async` (`approval_mode=auto`) → polled to `completed` → integrity
  check passed → draft actually updated with the real SuperDocs-generated
  content (a full Statement of Work, correct client name and fee) →
  `activity` logged.
- Correction path: submitted a same-session correction ("Actually, the
  engagement fee should be USD 30,000, not 25,000.") → classified
  `correction` (cue + value-overlap, both present) → flushed immediately
  (no silence-gap wait, per the correction-cue trigger) → all three
  occurrences of the fee in the document updated correctly, `25,000` →
  `30,000` → integrity passed → activity logged.
- Frontend, through the real browser (not just `curl`): built, served,
  opened via the Browser preview tool. Outside a real Zoom meeting the panel
  correctly shows the same "Not connected" state M2 established (expected —
  `@zoom/appssdk` doesn't work outside Zoom's client). Verified the new
  drafting UI itself by temporarily forcing a meeting UUID in-memory (never
  committed — reverted before considering this done, rebuilt bundle hash
  matches the clean build exactly), then drove the real workflow through
  the actual rendered React UI against the real backend: typed a transcript,
  clicked Send, watched it arrive via SSE (`transcript_received`), watched
  status flip `Idle → SuperDocs is editing… → Up to date` live, watched the
  activity tag and real draft content render. Zero console errors.

**Still needs the account holder, same category of gap M0/M2 had before live
confirmation:** reload the panel inside a real Zoom meeting and drive the
manual-entry workflow there. Everything provable from outside Zoom's client
is now proven; the SDK-connected path specifically only the account holder
can trigger.

**`make test`: 38 passed.** Full suite: `ManualTranscriptProvider`,
classifier, batcher, integrity checker, and `MeetingSession` (against a hand
-rolled `FakeSuperDocsClient` stub — no network, no key) — plus the pre-existing
M0/M1 webhook and SuperDocs-client tests.

**Milestone 3: complete**, with the one honestly-stated gap above. RTMS
remains entirely untouched (`ManualTranscriptProvider` was the only provider
exercised), so M0's earlier "unavailable" finding neither blocks nor is
resolved by anything here — exactly as the plan's isolation column predicted.

---

### M3 addendum — one real bug and one infra issue found via the account
### holder's own live test, both since fixed

The account holder tested the manual-entry workflow inside a real Zoom
meeting (SDK healthy, `inMeeting`, real meeting UUID) and Send produced no
visible change. Instrumented all ten stages of the pipeline end to end
(request handler through React state update) rather than guess, per their
explicit instruction. Findings, in order:

1. **A real app bug — `session_id` didn't match SuperDocs' own validation
   pattern.** Stages 0-8 all passed; stage 9 (`/v1/chat/async`'s response)
   came back **422**, every time, including on the trivial input `"hi"` —
   ruling out message content/length as the cause. The live error body was
   explicit: `session_id` must match `^[a-zA-Z0-9_.-]+$`. This app's
   `session_id` was built as `f"zoom-{meeting_uuid}-{timestamp}"`, embedding
   the raw Zoom meeting UUID directly — and real Zoom meeting UUIDs are
   base64-shaped, routinely containing `/`, `+`, `=` (confirmed: the account
   holder's real UUID ended in `==`). `upload-base64` doesn't enforce this
   pattern (why that call kept succeeding, masking the problem partway);
   `chat/async` does. **Every prior live verification in this session used
   a hand-typed test UUID with no special characters, so this never
   surfaced until a real Zoom meeting UUID was used — a real gap in this
   session's own earlier "live-verified" claim, worth stating plainly.**
   **Fix:** `session.py` now regex-substitutes any character outside
   `[a-zA-Z0-9_.-]` before building `session_id`. `self.meeting_uuid` keeps
   the real value for this app's own routing/registry. Confirmed fixed by
   replaying the account holder's exact meeting UUID shape and exact failing
   text against the running server: completes, drafts, same as every other
   live check this milestone.
2. **Not a bug — the dev tunnel had died.** A second reload attempt showed
   Zoom's own generic client-side error screen, not this app's. Checked the
   backend log: zero requests had arrived from the account holder's IP since
   the last restart — the app was never reached at all. The registered Home
   URL (`https://andrews-great-aruba-massive.trycloudflare.com`, a
   Cloudflare *quick* tunnel — ephemeral by design, dies whenever
   `cloudflared` restarts) returned Cloudflare's own Error 1033, confirming
   `cloudflared` wasn't running. Restarted it
   (`cloudflared tunnel --url http://localhost:8010`), got a new URL
   (`https://intellectual-sun-equally-oaks.trycloudflare.com`), and updated
   both the Home URL (Features → Surface) and the OAuth Redirect URL (Basic
   Information → OAuth Information) in the Marketplace app config to match
   — confirmed both saved (persisted across a fresh page reload) and the
   Home URL's own live reachability check passed. Same category of
   ephemeral-tunnel issue noted as a standing risk back in M0/M1's own
   PROGRESS.md entries; whoever picks this up next should expect to repeat
   this exact process again.

With the tunnel back up, the account holder reloaded and reached a real,
distinct third failure: **a red "Not Found" banner immediately on Send**,
status stuck on "Idle (reconnecting live updates…)".

3. **A second real app bug — a raw `/` in the meeting UUID breaks path
   routing, and percent-encoding does not fix it.** The account holder's
   actual live meeting UUID was `QkxusPH6QZm9FEK/fVQB/Q==` — containing a
   literal `/` in the middle, not just the `==` the session_id fix above
   already covered. The frontend interpolated this raw into every URL
   (`/api/meetings/${meetingUuid}/state` etc.); the `/` splits the path into
   extra segments FastAPI's router doesn't match, producing exactly the
   404 (`{"detail":"Not Found"}`) shown. **Confirmed directly, not assumed:**
   even a fully, correctly percent-encoded request (`%2F` for the slash)
   *also* 404s against this app's routes — Starlette's default path-parameter
   type doesn't accept encoded slashes unless the parameter is the route's
   final segment via the `:path` converter, which `{meeting_uuid}` isn't
   here (`/state`, `/transcript`, `/events` all follow it). Percent-encoding,
   the fix that would apply to almost any other special character, does not
   apply to this one. **Fix:** the frontend now base64url-encodes the
   meeting UUID before building any URL (`useMeetingSession.js`,
   `encodeMeetingUuid`) — base64url's alphabet never contains `/`, so this
   sidesteps the framework limitation rather than fighting it. Every route
   (`app/api/routes_session.py`, `app/api/routes_events.py`) decodes it back
   via a new shared `app/api/encoding.py::decode_meeting_uuid` before use.
   Verified the encode/decode round-trip byte-for-byte against the account
   holder's real UUID before touching the UI at all, then reproduced their
   exact failure (same UUID, same typed text) through the actual rendered
   React panel and confirmed it now completes — draft builds, activity
   logs, same as every other live check this milestone.

Both of these — the `session_id` pattern and the raw-`/` routing break —
are the same underlying fact (Zoom meeting UUIDs are base64-shaped and
contain URL-unsafe characters) surfacing at two different layers (a
SuperDocs-facing identifier; this app's own URL paths). Every prior
"live-verified" claim in this milestone used a hand-typed test UUID with at
most `==`, never a `/` — worth stating plainly as a real gap in this
session's own testing, closed only once a real Zoom meeting UUID was
actually used.

Instrumentation (backend `print`s at every stage, frontend `console.log`s in
`handleSend`/`useMeetingSession`) was added for this diagnosis and fully
removed afterward — `grep`-confirmed clean, rebuilt bundle hash matches the
pre-instrumentation build, `make test` still 38/38.

---

## Railway migration — replacing the Cloudflare quick tunnel

**Why, per explicit direction:** the Cloudflare quick tunnel dies on every
`cloudflared` restart, hands back a new random URL each time, and every
death meant a fresh round of Marketplace URL edits — three separate times
in this session alone (see the M3 addendum above). Not viable as the
Marketplace-facing URL going forward; the app needed a stable HTTPS
endpoint before continuing the SSE investigation, so that any live-update
failure could no longer be attributed to tunnel instability itself.

**What did not change:** `backend/app/`, `frontend/src/`, the SuperDocs
client, session management, the SSE routes — none of it. This section is
entirely packaging/config, plus three new files at the zoom-app root
(`Dockerfile`, `.dockerignore`, `.railwayignore`) and one Marketplace
config update per changed URL, documented below.

**Railway CLI:** installed via `brew install railway` (not previously
present), authenticated via `railway login`'s browser OAuth flow. Project
created via `railway init --name live-deliverable-zoom-app`, linked from
inside `zoom-app/` — deliberately *not* a GitHub-connected deploy, since
zoom-app has no git of its own (it lives inside Task 1's frozen repo) and a
GitHub integration would have meant connecting Railway to that repo, i.e.
touching Task 1's territory. `railway up` uploads the local directory
directly instead.

**`.railwayignore` added** (zoom-app has no `.gitignore` of its own; Task
1's root one covers `.env`/`.venv`/`node_modules` repo-wide, but whether
`railway up`'s git-aware ignore logic sees a parent repo's `.gitignore`
from a subdirectory with no git of its own isn't something to guess at
when the file in question is the actual API key — written explicit and
self-contained instead).

**Three build-config attempts, in order, each with real evidence before
moving to the next — not guessed past:**

1. **`nixpacks.toml`** (classic Nixpacks config). Deploy failed with a bare
   `reqwest error` first try; second try surfaced the real issue via
   `railway status --json`: the build used **Railpack** (Railway's newer
   default builder) and never even read the file — `nixpacksConfigPath:
   null` in the deployment manifest. Removed; wrong mechanism for the
   builder actually in use.
2. **`railpack.json`** (Railpack's own config format — confirmed via its
   real docs at railpack.com/config/file, not guessed from the nixpacks
   shape). Progress: the config *was* read this time (`Using config file
   railpack.json`), but `buildAptPackages: ["nodejs", "npm"]` pulled a
   ~180-package Debian apt tree (eslint, X11 libs, Perl modules — Debian's
   `nodejs` package is notoriously bloated) and the build ultimately failed
   with `ERROR: Could not open requirements file: ... requirements.txt` —
   Railpack's custom `steps.install` doesn't get project files by default
   (confirmed via the same docs: layers need an explicit `inputs` entry;
   the first attempt had none), and working out the correct multi-stage
   `inputs` chaining for a Python-provider + Node-base-image combination
   was heading into genuinely under-documented territory.
3. **`Dockerfile`** (standard multi-stage Python+Node build). Written,
   then **verified locally** with `docker build` + `docker run` before
   touching Railway again — health check, panel HTML, JS asset, and the
   base64url-encoded API route all confirmed 200 against the running
   container, on this machine, before spending another remote build. Only
   then pushed: Railway auto-detected the Dockerfile and built successfully
   on the first attempt. This is the "absolutely required" case the
   simplicity directive's Docker exception was written for — three
   config-file attempts each surfaced real, only-discoverable-by-trying
   behavior of Railway's current builder stack for this repo's split
   `backend/` + `frontend/` layout; Docker replaced guessing at
   undocumented multi-stage semantics with a standard, locally-verifiable
   pattern.

**`nixpacks.toml` and `railpack.json` both removed** — dead config once
Docker was confirmed working; leaving either in place would misrepresent
what's actually driving the build.

**Deployed:** `railway up --service live-deliverable-zoom-app`, builder
auto-detected as Docker, deploy succeeded first try. Domain generated via
`railway domain`: **`https://live-deliverable-zoom-app-production.up.railway.app`**.
Verified directly: `/health` → `{"status":"ok"}`, `/` → 200, and the
`/webhooks/zoom` `endpoint.url_validation` handshake responds correctly
(200, matching JSON shape) — though see the caveat below on secrets.

**Every Marketplace setting changed, each confirmed saved via a fresh page
reload (not just the in-page state) before moving to the next:**

| Setting | Where | Old value | New value |
|---|---|---|---|
| OAuth Redirect URL | Basic Information → OAuth Information | `https://intellectual-sun-equally-oaks.trycloudflare.com` | `https://live-deliverable-zoom-app-production.up.railway.app` |
| Home URL | Features → Surface | `https://intellectual-sun-equally-oaks.trycloudflare.com` | `https://live-deliverable-zoom-app-production.up.railway.app` |
| Event Subscription endpoint URL | Features → Access → Event Subscription → "M0 RTMS spike" | `https://andrews-great-aruba-massive.trycloudflare.com/webhooks/zoom` (already stale *before* this migration — an even older dead tunnel URL, never caught until now) | `https://live-deliverable-zoom-app-production.up.railway.app/webhooks/zoom` |
| OAuth Allow List | Basic Information → OAuth Information | — | Checked: empty, nothing to update |

**Not yet done — needs the account holder, same discipline as every
secret in this project:** `SUPERDOCS_API_KEY` and
`ZOOM_WEBHOOK_SECRET_TOKEN` are **not set on Railway yet** — confirmed via
`railway variable list` (only Railway's own auto-injected `RAILWAY_*` vars
present). The webhook handshake above returns 200 with a syntactically
correct response, but it's computed against the empty-string default
(`core/config.py`'s `zoom_webhook_secret_token: str = ""`), not a real
secret — Zoom's own verification of it will fail until the real token is
set. Set via `railway variable set KEY=value` run by the account holder in
their own terminal, or via the Railway dashboard's Variables tab — never
through this session, same rule as every other point this key has come up.

**Local dev is unaffected.** `make dev` still serves on `localhost:8010`
for iteration, unchanged. Railway is now what the Marketplace URLs point
to; local dev and the deployed instance are two independent things, same
as they were with the tunnel, just with a stable endpoint on the Marketplace
side now instead of one that dies on every restart.

**Update, later in the same project:** `SUPERDOCS_API_KEY` and
`ZOOM_WEBHOOK_SECRET_TOKEN` were since set on Railway by the account holder
(the "not yet done" note above is accurate for the moment it was written,
not the current state) — confirmed indirectly by real production traffic
succeeding in Milestone 4 and Milestone 5 below (real manual-transcript
submissions and real SuperDocs exports against the live Railway instance).

---

## Milestone 4 — RTMSTranscriptProvider: implemented and selectable, never exercised against Zoom

> **Read this heading precisely.** The provider is written to production
> quality and is selectable at runtime (`TRANSCRIPT_PROVIDER=rtms`, gated on
> `ZOOM_CLIENT_ID`/`ZOOM_CLIENT_SECRET` in `factory.py`). It has **never run
> against Zoom**: RTMS requires a purchased Zoom Developer Pack, which was
> not available on this account — confirmed with Zoom, and matching an open
> developer-forum report of the identical symptom. Its tests exercise it
> against a fake, never against the platform. "Production-ready" below means
> the code is complete, not that the integration is proven.

**Goal, restated precisely:** not to make RTMS work on this account — M0
already answered that (it doesn't, matching an open Zoom developer-forum
report of the identical symptom) — but to complete the `TranscriptProvider`
abstraction with a second, production-quality concrete implementation that
plugs into the exact same interface, plus the config-driven selection
between it and `ManualTranscriptProvider`.

**Config-driven selection, the one new branch point.** `TRANSCRIPT_PROVIDER`
(`manual` default, `rtms`) in `core/config.py`, read in exactly one place —
`transcript/factory.py::create_transcript_provider(settings)` — called from
`drafting/session.py::get_or_create_session`. `rtms` requested without both
`ZOOM_CLIENT_ID`/`ZOOM_CLIENT_SECRET` set, or an unrecognized value, falls
back to `ManualTranscriptProvider` with a logged warning rather than
attempting a connection guaranteed to fail. **`manual` is what's actually
deployed** — M0's finding still holds, nothing here changes that.

**`RTMSTranscriptProvider` (`transcript/rtms_provider.py`), built against
Zoom's documented websocket protocol** (`developers.zoom.us/blog/
realtime-mediastreams-websockets/`, read live during this milestone, not
from memory): webhook → `msg_type 1` signaling handshake (HMAC-SHA256 over
`{client_id},{meeting_uuid},{rtms_stream_id}`, keyed on the OAuth *client
secret* — a different scheme from the webhook signature above, keyed on the
webhook secret token) → `msg_type 2` response carrying the media server URL
→ `msg_type 3` media handshake (`media_type: 8` for transcript) → `msg_type
7` ready → `msg_type 17` transcript frames (`content.user_name`/`data`) →
`msg_type 12`/`13` keep-alive. Stream end is a separate `meeting.rtms_stopped`
webhook, not an in-band message. Two things this source didn't specify,
handled under a stated assumption rather than a silent guess: no interim/
final ASR flag on a frame (every frame is treated as final, timestamped at
server-side receipt — this app's Batcher already only ever wants final
transcript anyway), and no documented reconnect-after-drop semantics (this
provider re-fetches nothing beyond reopening the media socket, since
`rtms_stream_id` is stated as valid for the whole meeting instance).

**The core design decision — fallback without restarting the meeting,
without modifying `MeetingSession` at all.** `RTMSTranscriptProvider` owns
one internal `asyncio.Queue`, fed by both real RTMS frames *and* its own
`submit(text, speaker=None)` method (same shape as `ManualTranscriptProvider
.submit()`, not part of the `TranscriptProvider` Protocol). "Never connected"
and "connected then died" become the same mechanism — status flips to
`DEGRADED`, `submit()` stays open — so `MeetingSession._provider` never
needs reassignment. `get_or_create_session` sets `manual_provider = provider
if hasattr(provider, "submit") else None`, generalizing past an `isinstance`
list.

**A real bug found via this provider's own testing, not a hypothetical:**
`_read_frames`'s reconnect counter only incremented when `recv()` raised —
a silently stalled connection (no error, no data, e.g. a network partition)
would hang forever, never triggering reconnect. Fixed with
`read_timeout_seconds=45.0` wrapping `recv()` in `asyncio.wait_for`; locked
in by `test_silent_stall_is_caught_by_read_timeout_not_left_hanging`.

**Webhook dispatch** (`zoom/webhooks.py`): `meeting.rtms_started`/
`meeting.rtms_stopped` routed to the active session's provider via
`get_session` (not `get_or_create_session` — a webhook for a meeting whose
panel never loaded has nowhere to deliver the info), gated by `isinstance
(provider, RTMSTranscriptProvider)` so a stray `rtms_stopped` can never
`.stop()` a Manual-active session. Wrapped in a top-level `try/except` —
never 500s Zoom's own webhook caller.

**Panel-facing surface:** `GET /state` now includes `provider: {name,
status}` whenever `manual_provider` is set (true for both concrete
providers today). Frontend (`sdk.js`, `useMeetingSession.js`, `App.jsx`):
the 5 RTMS SDK capabilities + wrappers, a bounded 2–3s poll of `/state`
while `provider.status === "connecting"` (deliberately not a new SSE event
— a ≤20s, once-per-meeting need doesn't earn one), and a gated
`startRTMS()` trigger fired only once the *configured* provider is `rtms`
and the SDK reports it supported — calling it when manual-only is
configured would trigger Zoom's native "failed to access meeting content"
toast for nothing, per M0's own finding.

**Tests added:** `test_manual_provider.py` (direct coverage, previously only
exercised indirectly), `test_rtms_provider.py` (14 tests against an injected
fake websocket connector — handshake success/failure, the silent-stall fix,
reconnect-then-exhaustion, idempotent double-webhook, `submit()` at every
lifecycle stage), `test_transcript_factory.py` (6, all three
`TRANSCRIPT_PROVIDER` states), `test_provider_contract.py` (parametrized
across both concrete providers — demonstrates "the contract is solid" by
test, not claim), `test_webhooks.py` (+4, RTMS dispatch), `test_session.py`
(+2, the full batcher→classifier→SuperDocs→integrity pipeline fed through
`RTMSTranscriptProvider.submit()` instead of Manual's, proving it's
provider-agnostic by test). **62 → 77 tests, all green.**

**Verification — what's actually proven vs. not:**
- Full suite green throughout, not just at the end.
- Factory sanity-checked for all 3 `TRANSCRIPT_PROVIDER` states via a direct
  script — right class, no crash, in every case.
- **Real webhook replay** against a live local instance, real HTTP through
  the real FastAPI stack, a real `RTMSTranscriptProvider` configured with
  throwaway test secrets (never real ones): a correctly-signed
  `meeting.rtms_started` webhook reached the provider's real
  `on_rtms_started`, which made a real (failed — no real RTMS server exists
  to answer it) websocket connection attempt, was caught and logged exactly
  as designed, and the watchdog correctly resolved status to `DEGRADED`.
  `submit()` fallback confirmed still working via a real HTTP POST
  afterward. This is real proof of the *code path*, not of RTMS itself
  working — RTMS still cannot be exercised end-to-end in this environment.
- Redeployed to Railway (Docker rebuild) to ship this milestone's code;
  confirmed the new build was live via the new `provider` field appearing
  in production's `/state` response, and confirmed the deployed default
  (`manual`, unset `TRANSCRIPT_PROVIDER`) is provably unaffected — a real
  manual transcript submitted against production was accepted and reflected
  in state.
- **Live-in-Zoom check: attempted, not confirmed.** Opening the panel in a
  real meeting surfaced a Zoom-side generic error screen ("Something went
  wrong", error code `4CBD14E2-0x04-0000-0000-0B-0A-07`). Investigated
  immediately: the server itself was independently confirmed healthy at
  that exact moment via three separate paths — a Browser-pane fetch (real
  `{"status":"ok"}`), `railway status` reporting the service Online, and
  Railway's own public status page reporting no incident — while my own
  shell's `curl` to the same hostname failed DNS resolution, isolated to
  that one process. The most likely explanation is a stale cached Zoom
  webview from before the redeploy; the user was advised to hit Refresh /
  reopen the panel. **This was not re-confirmed working before Milestone 5
  work began**, and Milestone 5's own Railway redeploy (see that section)
  has since replaced this exact build on production anyway — stated here
  plainly as an open item that was never individually closed, not silently
  dropped. The one thing this milestone's live check *does* prove: the
  panel's JS bundle for this exact build loads cleanly with zero console
  errors outside Zoom, and every asset it references resolves 200 against
  production, confirmed directly via the Browser pane.

---

## Milestone 5 — Review Checkpoint + Export

**Goal:** an explicit, server-enforced human checkpoint between "the draft
is live" and "a file leaves the system" — the brief's own long-standing
requirement ("nothing leaves the room without a human saying so," design
doc §2/§17-18), never built until now. Export must only ever represent the
*current* approved draft; any change after approval must invalidate it and
require review again; the meeting must stay open and able to repeat the
cycle indefinitely.

**Two things learned from re-reading the actual code (not the original
design doc's guesses) that reshaped this milestone before writing any of
it:**
1. `SuperDocsClient` already had `export()` **and** `approve()` (built
   ahead of need in Milestone 1). `export()` — `POST /v1/documents/export`
   — was **already live-verified against the real API in Milestone 1**
   ("the requested edit's content actually landed," M1 above) and returns
   the file **bytes directly in the response body** — no job id, no
   polling, no signed download URL anywhere in this client. So export is
   one synchronous call, one route — not a trigger-then-poll shape.
2. `SuperDocsClient.approve()` was flagged **unreliable** in Milestone 1
   ("the job stayed `awaiting_approval` and export kept returning the
   pre-edit document"). **M5's review/approval gate is a pure in-house
   state machine on `MeetingSession` — it never calls `SuperDocsClient
   .approve()`.** Every M5 batch already runs `approval_mode="auto"`
   (unchanged M3 behavior), so nothing is ever awaiting SuperDocs-side
   approval in the first place. The new method is named `approve_draft()`,
   deliberately distinct so the two are never confused. `FakeSuperDocsClient`
   in tests has no `approve()` method at all — an accidental call would
   fail loudly with `AttributeError`, a free structural guard for a
   decision that shouldn't be relitigated.

**State machine — two new fields on `MeetingSession`, nothing else:**
`draft_version: int` (increments in exactly one place, `_handle_batch`'s
success path, right where `current_draft_html` is reassigned — so
`draft_version == len(activity)` holds as an exact invariant, not a
coincidence) and `approved_draft_version: int | None`. `export_ready` is a
derived property (`approved_draft_version == draft_version`), not a stored
flag — comparing two ints can't drift out of sync the way a separately
tracked boolean could. `changes_since_approval()` is a plain slice of the
existing `activity` list (`activity[approved_draft_version:draft_version]`)
— never a fabricated field-level diff ("Timeline: Nov 1 → Nov 15"), since
this codebase's own `IntegrityResult` has no before/after values anywhere
to draw one from. **No `gate.py` module** — an early draft of the design
doc planned one; the whole gate is small enough (two ints, one property,
one slice, two async methods) that a separate file would be premature
structure, and this milestone continues that restraint rather than
reversing it.

**`approve_draft(draft_version)`** raises — not a silent no-op — the
instant the caller's version no longer matches current state: the
server-side guard against approving content the user never actually saw (a
batch can land between the review screen rendering and the click). This is
the concrete fix for the exact race condition named in the brief.

**`export_draft()`** reuses the existing `_inflight_lock` (export is a
SuperDocs call for this `session_id`, same single-in-flight guarantee
`chat_async` already gets), checked twice — once before queuing, once again
after acquiring the lock, since an in-flight batch can complete and
invalidate approval while the export call was waiting its turn. **Does not
clear `approved_draft_version` on success** — the brief's invariant is
"draft changes invalidate approval," never "export invalidates approval,"
so the same approved version can be re-exported without re-approving, which
is also what makes "export doesn't end the session" true by construction
rather than by a special case.

**New routes** (`api/routes_review.py`, one file, two routes):
`POST /api/meetings/{uuid}/approve` (body `{draft_version}`, 409 on stale
version) and `POST /api/meetings/{uuid}/export` (409 if not currently
approved, 502 if SuperDocs itself fails, 200 with the real file bytes +
`Content-Disposition: attachment` on success). 409 matches the existing
convention (`routes_session.py`'s manual-provider-not-active check); 502 is
new precedent, deliberately, since this is the first route in the app that
synchronously awaits a SuperDocs call over HTTP.

**SSE, extended not replaced:** one new event, `draft_approved`, from
`approve_draft()`'s success path; the existing `draft_updated` event gains
a `draft_version` key at both its publish sites. No new "review required"
event — the frontend already has both numbers it needs from events already
firing, so a third event announcing an already-derivable transition would
be redundant. No changes to `routes_events.py` (the transport) at all.

**Frontend:** one more block inside `App.jsx`'s existing `draft-session`
section — no new `screens/`/`components/` directory, continuing the
established single-file pattern. Status line (approved vs. review-required),
the pending-changes list reusing the exact same `.activity-log`/`.tag`
markup the Activity section already uses (just a different slice of the
same real data), Approve/Export buttons gated on `exportReady`/`approving`/
`exporting`. `useMeetingSession.js`'s `exportDraft()` reads the response as
a `blob()` rather than a plain `<a href>`, specifically so a 409/502 JSON
error is caught and shown instead of silently downloading as a corrupted
file.

**Explicitly out of scope, stated up front:** template/multi-document
selection (no Setup screen or template picker exists anywhere in this app —
confirmed cut in M2/M3, and never promised to M5 despite the brief
mentioning "Multi-document"), a DOCX/PDF format picker (hardcoded
`format="docx"`; the parameter still threads through every layer, so a
picker is purely additive later), export retry/backoff (M6 territory,
matches `client.py`'s own stated scope), and cached/re-downloadable export
history (re-export just calls SuperDocs again; no per-session byte-caching
for a capability nobody asked for).

**Tests added:** `test_session.py` (+16 — new-draft-needs-review,
export-before-approval-rejected, approve-succeeds, stale-version-rejected,
export-after-approval-succeeds, post-approval-change-invalidates,
export-after-that-rejected, re-approval-works, exporting-twice-then-a-third-
transcript-still-processes (proves export doesn't end the session),
export-failure-publishes-error-and-preserves-approval,
activity-slice-correctness ×2, SSE event content ×2), plus a `FakeSuperDocsClient
.export()` method with no matching `.approve()`. New file
`test_routes_review.py` (6 — the HTTP-layer exception→status-code mapping,
which the session-layer tests alone can't prove; plus a dedicated test
constructing a real `httpx.HTTPStatusError` over a real `Authorization`
header to confirm the 502 handler's `str(exc)` never renders it). **77 → 98
tests, all green.**

**Verification — what's actually proven, distinguished by kind:**
- **Unit/integration (fake SuperDocs client):** full suite green, 98/98.
- **Real API, run once, end to end, against a live local instance with the
  real `SUPERDOCS_API_KEY` already configured in this machine's `.env`**
  (never read, typed, or transmitted by this session — confirmed present
  via a non-printing `grep` check only): submitted a real transcript →
  real SuperDocs edit landed → `GET /export` **rejected with 409** before
  any approval → `POST /approve` → `GET /export` **succeeded with 200**,
  and the returned bytes were independently confirmed to be a genuine
  36,737-byte Microsoft OOXML file (via the system `file` command, not
  assumed from a 200 status). Landed a second real correction → confirmed
  approval went stale (`export_ready: false`) → confirmed export **rejected
  again with 409** → re-approved → exported again, **200**, second real
  file. **Extracted the actual text from both `.docx` files and confirmed
  they differ correctly** — the first export literally contains "USD
  42,000", the second literally contains "USD 45,000," matching the two
  real corrections dictated — proving export reflects genuinely current
  content, not a cached or stale copy. Submitted a third real transcript
  after both exports and confirmed it processed normally (session/meeting
  never ended). This is the strongest verification tier available and was
  run exactly once, spending the minimum real SuperDocs operations needed
  to prove the new code path (export's own basic correctness was already
  proven once, in Milestone 1 — this did not re-derive that).
- **Docker build:** `docker build` + `docker run` succeeded (Docker Desktop
  had to be started first — it wasn't running). Confirmed the "rejected
  before approval" 409 path works inside the container with **zero**
  `SUPERDOCS_API_KEY` configured at all, proving the gate is checked before
  any SuperDocs credential is ever needed.
- **Secret exposure:** grepped the built frontend JS bundle for the API key
  and key-shaped strings (none found), confirmed `vite.config.js` has no
  env passthrough and no real `VITE_`-prefixed variable exists anywhere,
  and the dedicated `httpx.HTTPStatusError` test above confirms the 502
  error path specifically.
- **Diff/scope audit:** this repo has no git of its own (`zoom-app/` sits
  untracked inside the frozen Task 1 repo — confirmed via `git ls-files`
  returning nothing under it), so there is no `git diff` to inspect. Used
  file-modification-time as a proxy instead: every file touched this
  milestone matches exactly the file list in the implementation plan, no
  stray edits found.
- **Railway redeploy — a self-caught gap, corrected before this was written
  up as done.** The Docker build/run check above was local only; a first
  draft of this section claimed "Milestone 5's own Railway redeploy has
  superseded" the M4 build, which was false at the time it was written —
  no `railway up` had actually been run for this milestone's code yet.
  Caught while writing this section, not by the user. Fixed by actually
  deploying (`railway up --service live-deliverable-zoom-app`) and
  confirming the *new* code is what's live — `draft_version` appearing in
  production's `GET /state` (a key that doesn't exist in the M4-only
  build) — rather than trusting a 200 on `/health`, which would pass
  against the old build too. Production then re-checked directly: default
  provider still `manual`/`live` (unaffected), a fresh session's `/export`
  still correctly `409`s with zero SuperDocs cost, and a real manual
  transcript submission still returns `{"sequence": 1}` — all confirmed
  against `https://live-deliverable-zoom-app-production.up.railway.app`
  itself, not inferred.
- **Live-in-Zoom check: still not performed for Milestone 5.** Now that the
  actual Railway build is current, this is a real, closeable next step, not
  a moot one — but it needs the account holder inside a real meeting, same
  as M0/M2/M3's own live checks, and wasn't done as part of this write-up.
  Stated plainly as the one remaining verification tier, not overclaimed as
  done.

### Milestone 5 follow-up — the export result was invisible to the user

**The gap, reported directly from a real Zoom session:** the backend export
worked (200, real bytes), but the panel gave zero visible confirmation —
the old `exportDraft()` read the response as a Blob and fired a
programmatic `<a>.click()`, then just reverted the button label. No
filename, no size, no "this succeeded," and — critically — no way to know
whether a Zoom's embedded webview (not Chrome/Safari) actually honored a
JS-triggered download at all. Exactly the gap the brief named: *"do not
falsely claim a file was downloaded merely because the backend returned
200."*

**Fix, in one sentence:** stop trying to auto-trigger anything, and instead
show the user what's actually verified (export succeeded, this many bytes,
this content type) plus a real, standard, user-clicked `<a href>` pointing
at a new cached download route — never a claim that a download happened.

**Backend — `MeetingSession` gains `last_export`/`last_export_at`**, set at
the end of `export_draft()`'s existing success path (no other behavior in
that method changed — same lock, same double `export_ready` check, same
error handling). `state_snapshot()` exposes it as metadata only
(`content_type`, `size`, `exported_at` — never the bytes, which stay behind
the dedicated route). `export_draft()`'s success path now also publishes a
new `export_completed` SSE event — a correction to this milestone's
original reasoning, which assumed export "doesn't change any state
`MeetingSession` tracks." That stopped being true the moment `last_export`
became real tracked state; publishing it keeps this class internally
consistent (every state change gets published, the panel's own POST
response never directly mutates its UI — same policy `draft_approved`
already established, applied here rather than carved out as an exception).

**New route: `GET /api/meetings/{uuid}/export/download`**
(`routes_review.py`) — re-serves `session.last_export`, 404 (with a
specific message, not FastAPI's generic one) if nothing's been exported
yet, **no new SuperDocs call**. This is what the panel's "Download
document" link actually points at: a plain, real, navigable URL, not a
JS-driven Blob/ObjectURL. Deliberately *not* gated on current
`export_ready` — it serves whatever was actually, genuinely exported,
regardless of whether a newer unapproved draft exists since (that export
was still real when it happened); the frontend, not this route, decides
whether to keep advertising the link once a newer draft makes the
confirmation stale. No new auth mechanism — same posture as every other
route here, the `meeting_uuid` itself is the only correlation key this app
has ever used; a separate token/short-lived-URL scheme would be new
architecture this fix doesn't need. Filename changed from the generic
`draft.docx` to `Meeting-Draft.docx`, drawn from the starter document's own
real `<h1>Meeting Draft</h1>` — not fabricated, not a template title this
app has no data for.

**Frontend:** `exportDraft()` no longer touches the DOM or creates any
Blob/ObjectURL at all — it only confirms the POST succeeded; `state`
updates via the new `export_completed` SSE event, same "no optimistic
local mutation" policy already governing every other action in this hook.
`App.jsx` renders, once `session.exportReady && session.lastExport`: "✓
Document exported", `Meeting-Draft.docx — 36.7 KB · exported 12s ago`, and
a real `<a href={session.exportDownloadUrl} download="Meeting-Draft.docx">
Download document</a>` — never "Downloaded successfully." The confirmation
block is hidden (not the download route — see above) the moment a new,
unapproved draft exists, so it never sits next to a "review required"
banner claiming something contradictory. The Export button stays live
throughout (relabels to "Export again" once a result exists) so a fresh
re-export is always possible, not just a one-shot action; both
approve/export buttons keep their existing disabled-while-in-flight guards
— double-export was already prevented before this fix and needed no
change.

**Tests added:** `test_session.py` (+4 — `last_export` gets set on success,
`state_snapshot()` carries metadata but never bytes, a failed second export
doesn't clobber a genuinely successful first one, `export_completed` is
published with the right shape) and `test_routes_review.py` (+3 — 404
before anything's exported, the download route serves the cached bytes
with zero additional SuperDocs calls, and a stale-approval scenario still
serves the previously-real export rather than erasing it). **105 tests, up
from 98, all green.**

**Verification, by tier — same discipline as the rest of this milestone:**
- Unit/integration: 105/105.
- **Real API, run locally, twice** (once against the fresh route, once
  through a full stale→re-approve→re-export cycle, reusing the same
  session — not two independent real drafts): confirmed the `POST /export`
  round-trip took ~1.1s (a real SuperDocs call) while the new `GET
  .../export/download` immediately after took ~0.015s and returned
  byte-identical content — direct, measured evidence it's served from
  cache, not re-derived from a claim. Landed a second real correction,
  confirmed `export_ready` flipped false and `POST /export` correctly
  409'd again, **and confirmed the previously-exported file remained
  retrievable via the download route throughout** (historical export,
  correctly not erased by a newer unapproved draft). Re-approved, exported
  again, extracted the new file's real text and confirmed the correction
  ("USD 9,000") actually landed, and confirmed the download route now
  serves *that* file.
- **Real API, run once against production** after deploying: submitted a
  real transcript, approved, exported (real OOXML confirmed), then hit the
  download route and again measured it as clearly faster (~0.4s vs. a full
  export's several seconds, over the network this time, not localhost) and
  byte-identical to the fresh export.
- Docker: build succeeded, same JS bundle hash as the local build
  (reproducible).
- Frontend build: clean, zero errors.
- Diff audit: file-mtime proxy again (still no git tracking for this repo)
  — exactly the 9 files this fix actually touched, nothing stray.
- **Deployed to Railway, confirmed live** via the new download route's
  *specific* 404 message (`"nothing has been exported yet for this
  meeting"`) — not just a generic 404, which the pre-fix build would also
  return for an undefined path, and would have been a false-positive
  signal.
- **What this does NOT prove, stated exactly as precisely as the brief
  asked for:** this confirms the export result is generated, cached, and
  made available via a real, working, verified HTTP endpoint — it does
  **not** confirm that Zoom's embedded webview actually honors the
  `download` attribute on a real user click, since that can only be
  observed by the account holder inside a real meeting. **Precise
  claim, not overclaimed:** the document is reliably made available to the
  user via a real link; whether the specific in-Zoom click-to-save gesture
  behaves as expected is part of the still-open live-in-Zoom check above,
  not newly resolved by this fix.

---

## P0 investigation — is real Zoom RTMS reachable now, and if not, why exactly

**Objective, stated precisely:** confirm or refute, with current evidence, whether the RTMS-powered live-transcript path (the intended product experience per the brief — not `ManualTranscriptProvider`, which is explicitly a development fallback) can work on this account. Not a code investigation — M0 already proved every piece of this repo's own configuration correct. This round re-checks whether anything upstream of this repo (account entitlement, Zoom's own platform state) has changed since M0, using current sources, not memory.

**No code was changed in this investigation.** Per its own governing instruction: if the blocker is account entitlement, stop modifying architecture and document instead.

### Finding 1 — production has never been configured to attempt RTMS at all

Checked directly: `railway variables --service live-deliverable-zoom-app --kv` (names only, no values printed or handled). Full list present: `RAILWAY_*` (auto-injected), `SUPERDOCS_API_KEY`, `ZOOM_WEBHOOK_SECRET_TOKEN`. **`TRANSCRIPT_PROVIDER`, `ZOOM_CLIENT_ID`, `ZOOM_CLIENT_SECRET` are absent.** `core/config.py`'s `Settings.transcript_provider` defaults to `"manual"` when unset — so every session ever created on the deployed instance, since M4 shipped, has used `ManualTranscriptProvider`. This is a separate, prior fact from account entitlement: even if the account had full RTMS access today, production would still never attempt it, because nothing has ever told it to. Not a bug — `TRANSCRIPT_PROVIDER=rtms` plus real `ZOOM_CLIENT_ID`/`ZOOM_CLIENT_SECRET` (the Marketplace app's OAuth Client ID/Secret, App Credentials page) were always meant to be set by the account holder once RTMS was worth attempting (`.env.example`'s own M4 comment), and that step was never reached.

### Finding 2 — current, real evidence: RTMS requires a purchased Zoom Developer Pack, confirmed by Zoom staff, dated within the last two months

Two Zoom Developer Forum threads, fetched directly (not summarized from memory or a stale search index):

- [devforum.zoom.us/t/enable-rtms-for-app-id-3p7ovtwhqhaadmpc8lxaag/144375](https://devforum.zoom.us/t/enable-rtms-for-app-id-3p7ovtwhqhaadmpc8lxaag/144375) — a developer with an "Active" Developer Pack (20 credits) still got RTMS enablement refused. Zoom staff (Chun Siong), quoted directly: *"there is no developer pack associated with your account yet"* — and even after the developer purchased "the Zoom Build Platform" (a different product), Zoom staff reiterated: *"you need Zoom Developer Pack."* Dated June 23, 2026.
- [devforum.zoom.us/t/how-to-enable-rtms-real-time-media-streams-on-business-account/142486](https://devforum.zoom.us/t/how-to-enable-rtms-real-time-media-streams-on-business-account/142486) — a developer on a paid Business plan (10 licenses) found RTMS did not appear in Account Settings at all. Zoom staff (Joan) directed him to a separate RTMS enablement form; after escalation, staff (Elisa) manually enabled it and stated directly: *"RTMS is a paid add-on."* Full resolution took roughly a month.

Both threads are current (June 2026, within the last two months of this writeup), both from Zoom staff directly (not other developers guessing), and both independently converge on the same two facts: **(a) RTMS requires a purchased Zoom Developer Pack — a paid product, not included in a standard paid Business plan — and (b) even with one, enablement is a separate manual step performed by Zoom staff, not a self-service toggle.** This corroborates and upgrades M0's own tentative, hedged finding ("not ruled out: Developer Pack credits, never obtained this session") from an open hypothesis to a confirmed, current, multiple-source-evidenced requirement.

**Confirmed directly with the project owner (not inferred): no Zoom Developer Pack has been purchased for this account, as of this writeup.** Nothing has changed since M0 on this specific axis.

### Conclusion — classification

**Category A: Account/entitlement blocker.** Not B/C/D (every Marketplace scope, capability, webhook config, OAuth field, and signature check was independently verified correct in M0 — see that section's own line-by-line audit) and not E/F/G (the client-side `startRTMS()` call resolves, the correct native Zoom error toast appears, meaning the request reaches Zoom's platform and is being actively refused there, not silently misrouted by a bug on our side) and not H (unrelated to Railway/deployment — Finding 1 above is a separate, additive fact, not the root cause: even a perfectly-configured Railway deployment would still hit the same account-level refusal the instant RTMS actually engaged).

**A fresh live-meeting test (Step 6/7/11) was deliberately not run this round.** M0 already ran that exact test — real meeting, `startRTMS()` called for real, native Zoom error toast observed, 30+ seconds monitored for a webhook that never arrived, every prerequisite independently confirmed correct first. Nothing about the account's entitlement has changed since (confirmed above). Re-running the identical test against an unchanged root cause would spend the account holder's time for a result already known, not new evidence — the honest call here is to not ask for that, not to claim the check happened, and not to skip it silently either. If a Developer Pack is purchased and RTMS is enabled by Zoom staff, a fresh end-to-end test (real speech → real transcript → visible draft update, Step 11's full acceptance criteria) becomes genuinely necessary and is the very next action, not something this investigation can substitute for with reasoning about an unchanged account.

### What remains correct and untouched

`TranscriptProvider` / `RTMSTranscriptProvider` / `ManualTranscriptProvider` architecture — unchanged, not touched this round. `RTMSTranscriptProvider` remains real, production-capable code, fully unit-tested against the documented protocol (M4), ready to activate the moment the account can reach it — exactly the position M0 and M4 already left it in, restated rather than revised. No new transcription provider was invented, no browser audio capture added, no fake RTMS events, no pretending the manual path is automatic — all explicitly out of scope per this investigation's own governing rule, and none of them would fix an account-level refusal regardless.

---

## Milestone 6 — Vexa as the default live-transcription provider

**Goal:** live listening for the deliverable during the call. Vexa joins
the Zoom meeting as a bot and streams transcript into the EXISTING
MeetingSession → draft pipeline; the Zoom side panel gets one explicit
**Start listening** control. Vexa's only responsibility is listening —
no drafting, no summarizing, no document logic lives in or near the
adapter.

### Vexa verification trail (what the adapter was built against — current source, not old docs)

- **Repo/version:** `Vexa-ai/vexa` on GitHub, main @ `fde7dfb7`
  (2026-08-08, pushed the day this milestone was built), version 0.12.
  Fork candidates (`On-Behalf-AI/vexa`, `MeetingMind-AI/vexa`,
  `shaneholloman/vexa`) checked via the GitHub API: 0 stars each, stale —
  `Vexa-ai/vexa` (2663 stars, active) is canonical.
- **Zoom join mechanism:** web-client guest join (no SDK setup, no
  Marketplace app). The bot's Playwright browser navigates the meeting
  URL — `join/src/zoom/join.ts::buildZoomWebClientUrl` rewrites canonical
  `zoom.us/j/<id>?pwd=...` to `app.zoom.us/wc/<id>/join` and joins as a
  named guest, mic muted, audio enabled to receive the mixed stream.
  Speaker attribution is DOM active-speaker polling (~250ms), matched
  temporally to transcription turns. Human gates exist: reCAPTCHA and
  Zoom's "automated bots aren't allowed / must use Zoom RTMS" wall leave
  the bot in `needs_human_help` until a human clears them via noVNC.
- **API used (public gateway surface, verified in source):**
  - `POST /bots` `{platform:"zoom", native_meeting_id, meeting_url,
    passcode?, bot_name, language, transcribe_enabled}` → 201
    MeetingResponse. `meeting_url` is REQUIRED for zoom (bot_spawn/
    router.py: "required for zoom/jitsi"); when absent, the URL is parsed
    to derive platform + id + passcode (collector/meeting_link.py: zoom =
    9–11 digits, host containing "zoom"). `transcribe_enabled:false` is
    capture-only — we always send true.
  - `DELETE /bots/{platform}/{native_meeting_id}` → stop.
  - `GET /transcripts/{platform}/{native_meeting_id}` → TranscriptionResponse
    with `segments[]` (TranscriptionSegment: text, speaker, completed,
    start/end, created_at, absolute_start_time). `completed:true` marks a
    FINAL segment.
  - `ws(s)://<gateway>/ws`, auth header `x-api-key`, subscribe
    `{action:"subscribe", meetings:[{platform, native_id}]}`; live data
    `{type:"transcript", confirmed[], pending[]}` (per-speaker bundle),
    `{type:"transcription_segment", ...}`, `{type:"meeting.status",
    payload:{status}}` (ws.v1 contract). MeetingStatus enum: requested →
    joining → awaiting_admission → active → stopping → completed/failed,
    plus needs_human_help.
- **Transcript mechanism:** the /ws stream is realtime (sub-second,
  per-segment pushes); REST polling of GET /transcripts is the fallback.
  The adapter uses WS first, falls back to polling on exhausted reconnects
  — transport is logged, never misrepresented.
- **Transcription (speech→text):** Vexa's bot captures audio and sends it
  to a transcription service. Self-hosting transcription needs a GPU
  (explicitly NOT deployed here) or the hosted Vexa transcription service
  (free token at vexa.ai/account, `TRANSCRIPTION_SERVICE_URL`/`_TOKEN`);
  Vexa Lite also bundles a CPU faster-whisper variant (`LOCAL_STT=1`).
  **No separate Whisper deployment was added by this milestone** — Vexa
  is the single transcription path.

### Hosting decision and the exact blocker (state plainly, no fabrication)

- **Hosted vexa.ai:** the hosted API (api.cloud.vexa.ai) currently
  supports Google Meet and Microsoft Teams only — **Zoom is "coming
  soon"** (verified on vexa.ai, 2026-08-08). The required Zoom path is
  not available there today. A free $5 credit exists (no credit card),
  so cost is not the blocker for the hosted path — Zoom support is.
- **Self-host on Railway:** the current smallest supported self-host
  shape is **Vexa Lite** (v0.12, deploy/lite/Dockerfile.lite): one image
  but containing the Playwright Chromium bot + Xvfb + PulseAudio + ffmpeg,
  the Node bot process, five Python services (gateway/admin/meeting-api/
  runtime/agent-api), a built-from-source Valkey, supervisord — plus
  external PostgreSQL + MinIO sidecars. Full compose needs 8 vCPU/16GB
  (README). Lite is lighter but is still a headful-browser stack with a
  realistic floor of ~1.5–2GB RAM under load.
- **Railway trial constraint (stated in the task, treated as hard):**
  2 vCPU / 0.5 GB RAM per service, ~$5 free usage. The current Vexa
  Zoom-capable deployment cannot operate within it.
- **Blocker (STOP condition 2/3 from the task):** the only current Vexa
  deployment that performs the required Zoom transcription is the
  self-hosted stack, whose minimum footprint exceeds the Railway trial
  service budget; the hosted Vexa API does not yet support Zoom. There is
  no lightweight supported option within the task's constraints.
  **Nothing about this was papered over:** the adapter, tests, config,
  and degraded UI are real and verified; live listening reports "Live
  transcription unavailable" honestly until a Vexa host exists.
- **What unblocks it (for the record, not acted on):** (a) Zoom support
  landing on api.cloud.vexa.ai (then VEXA_API_BASE_URL/KEY point there —
  zero extra infrastructure, fits Railway trial), or (b) a free-tier
  external VM big enough for Vexa Lite (no spend, but outside this task's
  Railway constraint). The provider adapter is identical for both.

### The adapter

`backend/app/transcript/vexa_provider.py` — a THIN adapter, same shape as
the other two providers:

- `start(meeting_context)` records the meeting UUID and does NOTHING else
  — opening the panel never spawns a bot. Listening is the explicit
  Start-listening action.
- `begin_listening(meeting_number=, meeting_url=)` constructs the join
  URL (`https://zoom.us/j/<id>`, which Vexa rewrites to its web-client
  flow), POSTs /bots, spawns the consumer. CONNECTING until the first
  transcript segment (or meeting.status=active) flips it LIVE.
- Consumer: `/ws` subscribe (realtime) with bounded reconnect
  (attempts/backoff); exhausted → REST polling fallback; repeated poll
  failures → DEGRADED. Interim/pending segments are never emitted (the
  Batcher's final-only rule — only `confirmed`/`completed:true` segments
  enter the pipeline).
- Dedup: segments carry no id, so duplicates (WS re-delivery, poll
  re-reads) are recognized by (speaker, text, start-time) and emitted
  once.
- `stop()` cancels the consumer, closes the socket, DELETEs the bot
  (`/bots/zoom/<id>`) so none is orphaned, status STOPPED.
- `submit()` — manual override stays open in every state, exactly like
  Manual/RTMS (this is what keeps the manual fallback route working with
  zero route changes).
- Never raises out of start()/begin_listening(); every failure resolves
  to DEGRADED and the panel says so truthfully.

Session/route surface:

- `MeetingSession.start_listening()/stop_listening()` — explicit
  lifecycle; ValueError (→ 409) when the active provider has no
  live-listening capability (Manual; RTMS starts from Zoom's webhook).
- `routes_listen.py`: `POST /api/meetings/{uuid}/listen` (body:
  meeting_number/meeting_url — the panel sends the meeting number it
  already has from getMeetingContext; nobody types anything) and
  `POST .../listen/stop`.
- Frontend: one control block when provider is vexa — Start listening /
  Stop listening / Try again, statuses Ready → Connecting… → ● Live →
  Stopped / "Live transcription unavailable" (degraded). Manual input
  box and review/approve/export unchanged.

### Configuration (names only — never values)

`TRANSCRIPT_PROVIDER` (default now **vexa**; manual, rtms selectable),
`VEXA_API_BASE_URL`, `VEXA_API_KEY`, `VEXA_BOT_NAME`, `VEXA_LANGUAGE`,
`VEXA_POLL_INTERVAL_SECONDS`. Documented in `.env.example`. Missing
Vexa config never crashes: the provider constructs, the panel shows
"Live transcription unavailable", manual input stays available.

### Zoom meeting identifier

The panel's `getMeetingContext().meetingNumber` (numeric ID, from the SDK
— never typed by the user) is what Vexa needs, wrapped in a server-side
join URL. Known limitation: Zoom meetings with a passcode need `?pwd=`
or the `passcode` field, which the SDK context does not expose — such
meetings degrade honestly rather than silently failing. Meeting URLs
are logged host/path-only, never the query string (no passcode in logs).

### Tests

136 passing (baseline 105 + 31 new): `test_vexa_provider.py` (init,
config, missing config, start-doesn't-spawn, spawn payload asserted
against the verified API contract, spawn failure→degraded, stop DELETEs
bot, WS confirmed delivery + ordering + sequence, pending never emitted,
polling fallback + dedup, WS-drop→polling, poll-failure→degraded,
meeting.status drives live/degraded) and `test_vexa_session.py` (Vexa
segments drive the existing draft pipeline — two utterances, two batches,
correction reflected in final draft; manual submit stays open on a Vexa
session; start/stop lifecycle; /state exposes provider; listen routes:
200 connecting, degraded without identifier, 409 on manual session).
Factory tests updated for the new default (vexa); provider-contract tests
now parametrized across all three providers. All Vexa tests use mocks —
no paid service is ever called by the suite.

### Builds

- Frontend: `npm run build` clean (vite, 30 modules).
- Docker: `docker build` clean; container boots, `/health` OK, panel
  served at `/`, unconfigured-Vexa warning logged, no crash.
- Full suite: `make test` → 136 passed.

### Deployment status and real-Zoom acceptance

**Backend redeploy to Railway:** not yet run at the time of this writeup
— see the current session's report for whether `railway up` ran.

**Real Zoom acceptance test: NOT RUN — blocked by the hosting blocker
above.** Without a running Vexa host there is nothing to join the meeting,
so claiming "Start listening → Live → speech reaches the draft" would be
fabrication. What IS verified: the full path with mocks (Vexa API payloads
per the current contract, WS transcript flow, pipeline integration,
corrections reaching the draft), the degraded-state UX (honest "Live
transcription unavailable", manual fallback live), and the existing
M0–M5 real-meeting/real-API results. Observed latency: N/A (no live
Vexa host; Vexa's own transport is sub-second WS, poll fallback
VEXA_POLL_INTERVAL_SECONDS).

### RTMS status (unchanged)

RTMS remains implemented (`RTMSTranscriptProvider` + webhook handling +
signature verification + lifecycle/reconnect behavior + tests) and
selectable via `TRANSCRIPT_PROVIDER=rtms`. Currently BLOCKED at the
account level (Zoom RTMS requires a purchased Developer Pack — see the
P0 investigation above). Switching to it later is configuration, not a
rewrite.

### Known limitations (factual)

1. Live Vexa listening cannot be activated from this Railway trial until
   a Vexa host exists (blocker above); degraded state is the truthful
   default.
2. Passcode-protected Zoom meetings cannot be joined — the SDK context
   has no passcode.
3. Some Zoom meetings gate anonymous bots (reCAPTCHA / "must use Zoom
   RTMS" wall) — Vexa reports needs_human_help; the meeting must admit
   the bot manually (noVNC), matching Zoom's own platform behavior.
4. Vexa segments have no stable id — dedup is by content key
   (speaker+text+start); two identical utterances at identical offsets
   are theoretically collapsible (not observed; acceptable for one
   concurrent meeting).
5. Same M0 decision as ever: session state is in-memory; a backend
   restart loses in-progress sessions (accepted, stated).

---

## Milestone 7 — the capture path that actually ships

Written after the fact, on 2026-08-24, because this log stopped at M6 while
the system moved on. Everything here is drawn from
`ACCORD_FINAL_SUBMISSION_AUDIT.md`, which verified each claim against the
code or a live run. Nothing is reconstructed from memory, and where something
was not independently verified it says so.

**Why a local capture provider at all.** M0 established RTMS was unavailable
on this account and M4 built the provider anyway, against the Protocol, for
when it is granted. M6 made Vexa the default. Vexa's own limitations —
passcode-protected meetings it cannot join, meetings that gate anonymous
bots behind a reCAPTCHA wall — meant a demo could fail for reasons that had
nothing to do with this codebase. A capture path with no third-party joiner
and no platform entitlement removes that whole class of dependency.

**A7-1 — the control channel is outbound, and authenticated.** The helper
dials the backend, not the reverse: `WSS /api/ws/helper?token=…`
(`backend/app/api/routes_helper.py`). The server never needs a route to a
laptop, and nothing has to be open on the user's machine. A wrong or missing
token closes the socket with code 4401 before any message is processed. As of
this milestone the token comparison uses `hmac.compare_digest` rather than
`!=`, so the handshake does not leak the length of a matching prefix through
timing.

**A7-2 — helper lifecycle is two messages, not a daemon.** `START` carries the
meeting UUID; the helper spawns the Swift capture binary as a subprocess with
`--uuid` and `--backend` and logs `capture process spawned pid=…`. `STOP`
sends `SIGTERM` (`helper/helper.py:108`), which the capture side observes
through its `StopFlag` loop, flushing whatever partial chunk it holds before
exiting. Deliberately no installer and no login item: the user starts it,
sees it, and kills it. That is stated as a limitation in the README rather
than dressed up.

**A7-3 — chunks end at a pause, not on a clock.** The capture binary
originally emitted fixed 4s slices, then fixed 6s. Both cut mid-sentence, and
Whisper does not return half a sentence — handed a truncated fragment it
invents an ending. Measured directly against Groq on the committed 77s SOW
audio, transcribing each strategy's chunks:

| strategy | chunks | cut mid-sentence | invented endings | `$45,000` formatting |
|---|---|---|---|---|
| fixed 6s | 13 | 9 of 13 | yes | kept |
| fixed 10s | 8 | most | yes | **lost** — one chunk came back with no punctuation and spelled-out numbers |
| pause-bounded, 12s ceiling | 9 | **0** | **none** | kept |

Longer chunks alone make it worse. It is where the boundary falls that
matters. `AudioChunkSender.endsOnAPause()` therefore treats `chunkSize` as a
**ceiling** and the pause as the trigger: a chunk ends once the trailing 0.6s
is below an amplitude floor, subject to a 3s minimum. A room with constant
background noise degrades to exactly the fixed-slice behaviour this replaced
— never worse.

Concrete failure this fixed: a 6s boundary once fell between `"delivered by"`
and `"30th"`, so the word "October" landed in neither chunk's transcript. The
document read "September 30th", because that is what the pipeline was
honestly given.

**A7-4 — transcription, and one thing deliberately not done.** Groq Whisper
`large-v3`, `language=en` pinned because short fragments otherwise pay a
detection cost and can pick a wrong language. Each chunk replays the previous
chunk's last 1.5s so a boundary word is heard whole at least once; the repeat
is stripped server-side by `_dedupe_overlap` (`SequenceMatcher`, 0.75).
Whisper answers near-silence with caption-style sign-offs — "we'll see you
next time" — which are stripped at the boundary, after one reached a live
export.

There is **no dynamic Whisper prompt**, and that is a decision rather than an
omission. Feeding the previous transcript back as context made Whisper treat
corrupted boundary text as confirmed prior speech and compound it into a
self-reinforcing hallucination. The reasoning is recorded at
`routes_audio.py:142`. Boundary context comes from overlapping the **audio**
instead: the model re-hears the real sound rather than being told what it
previously guessed.

**A7-5 — the seam, named exactly.** Capture does not reach into the pipeline.
`POST /api/meetings/{uuid}/audio` transcribes, then hands the text to the
existing abstraction (`routes_audio.py:187`):

```python
event = await session.manual_provider.submit(text)
```

`ManualTranscriptProvider.submit()` returns a `TranscriptEvent` — the same
shape Vexa and RTMS produce. Past that call nothing knows or cares that the
audio came from ScreenCaptureKit. The Batcher, the classifier, the validation
gate and the export path are unchanged from M3–M5 and were not touched to
make this work.

That is the point of the M3 Protocol finally being paid off: **the capture
boundary is swappable.** A production-approved provider — RTMS when the
Developer Pack exists, or anything else satisfying `TranscriptProvider` — can
occupy it without touching a line downstream.

**A7-6 — what this milestone does NOT claim.** The Zoom app is in beta
review; only its author can install it, so this is not marketplace-ready
public distribution. Live capture is macOS-only and needs screen-recording
permission. RTMS remains unexercised against Zoom. Document generation
downstream still shows the run-to-run variance recorded as issue 11 in
`SUPERDOCS_BUGS.md`, and that finding stands unsoftened.
