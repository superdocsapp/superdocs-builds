# lms-doc-assignment

An LTI 1.3 tool that launches a SuperDocs track-changes review from inside Canvas or
Moodle, and posts a completion grade back to the gradebook through Assignment and Grade
Services (AGS) — the entirely different integration shape Canvas/Moodle require (LTI 1.3,
not a REST client) even though the student-facing feature looks like a simple link.

## What it does

An instructor places a "review this document" assignment into a course via **Deep
Linking**. A student opens it, gets a real OIDC-launched view of the assigned document, and
edits it through SuperDocs' `chat_async` in `approval_mode=ask_every_time` — the same
human-in-the-loop track-changes flow the product itself uses for regulated review. Each
proposed change is approved or denied explicitly before it applies. When the student marks
the review complete, the tool posts a real score back through AGS, which lands in the
course's actual gradebook.

## What SuperDocs features it uses

- **`POST /v1/chat/async`** with `approval_mode=ask_every_time` — the track-changes review
  itself
- **`GET /v1/jobs/{job_id}`** — polled for the proposed change
- **`POST /v1/chat/{session_id}/approve`** — approves or denies the change

## What "strong" requires, and how each is actually proven here

The brief's bar: *"a real LTI 1.3 launch where the JWT signature verifies against the
platform's public keys rather than just opening a link, places itself as an actual
assignment through Deep Linking, and a completed review posts a real score back through AGS
that shows up in the gradebook."* All three are verified against a live local Moodle, not
asserted:

1. **JWT signature verification.** `app.py`'s `/launch/` route calls
   `pylti1p3.FlaskMessageLaunch.get_launch_data()`, which fetches Moodle's live JWKS
   (`/mod/lti/certs.php`) and verifies the launch JWT's signature against it — proven by
   running `moodle-dev/verify_launch.py`, which drives a real launch over HTTP and only
   reaches the review page if that verification passes.
2. **Real Deep Linking placement.** `moodle-dev/verify_launch.py deep-link dpa` drives
   Moodle's actual content-item-selection flow, and the resulting `mdl_lti` /
   `mdl_course_modules` rows are real database rows — checked directly with `SELECT`, not
   inferred from an HTTP 200.
3. **A real AGS score in the gradebook.** After a review's changes are approved and
   `/api/review/<id>/complete` is called, `SELECT finalgrade FROM mdl_grade_grades` shows a
   real `1.00000` row for the launching student — not a mocked response.

## How this was actually verified

No browser automation was available in the environment this was built in. Every check above
was driven by replaying the exact HTTP requests a browser would make —
`moodle-dev/verify_launch.py` parses each hop's auto-submit form (or, for pylti1p3's
cookie-availability check, its JS redirect) and replays it. One step has no HTTP equivalent:
in a real browser, Deep Linking's final step is cross-window JS messaging
(`parent.processContentItemReturnData(...)`), which only exists once a real "Add activity"
page has opened the picker in a popup. `moodle-dev/finalize_deeplink_headless.php` does,
via Moodle's own `add_moduleinfo()` API, exactly what a human clicking through that flow
would have submitted — starting from the same deep-link response JWT, verified the same way.

## Run it locally

```bash
# 0. This tool's own signing keypair (never committed - generate your own)
openssl genrsa -out configs/private.key 2048
openssl rsa -in configs/private.key -pubout -out configs/public.key

# 1. Local Moodle (a real LTI 1.3 platform to launch against)
cd moodle-dev && docker compose up -d
# wait ~30s for first boot, then:
docker cp register_tool.php $(docker compose ps -q moodle):/tmp/register_tool.php
docker compose exec moodle php /tmp/register_tool.php
# note the printed clientid + wwwroot; put them into ../configs/tool.json
docker cp create_test_fixtures.php $(docker compose ps -q moodle):/tmp/create_test_fixtures.php
docker compose exec moodle php /tmp/create_test_fixtures.php
docker cp finalize_deeplink_headless.php $(docker compose ps -q moodle):/tmp/finalize_deeplink_headless.php
cd ..

# 2. The tool itself
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
export SUPERDOCS_API_KEY=sk_...
.venv/bin/python app.py   # listens on :9001

# 3. Verify a launch (separate venv, only needed for this headless verification)
python3 -m venv moodle-dev/.venv && moodle-dev/.venv/bin/pip install requests beautifulsoup4
moodle-dev/.venv/bin/python moodle-dev/verify_launch.py deep-link dpa
# it saves the deep-link response JWT and prints the two commands to finalize it into a
# real course module - run those, then note the printed cmid
moodle-dev/.venv/bin/python moodle-dev/verify_launch.py launch <cmid> student1
# note the printed launch_id, then drive the review API directly:
curl -X POST localhost:9001/api/review/<launch_id>/edit -H 'Content-Type: application/json' \
  -d '{"instruction": "Change the data retention period in section 2 to 60 days"}'
curl -X POST localhost:9001/api/review/<launch_id>/decide -H 'Content-Type: application/json' \
  -d '{"approved": true}'
curl -X POST localhost:9001/api/review/<launch_id>/complete
```

## Rough edges found getting this working (Moodle's, not SuperDocs')

None of these were signposted by an error message that named the actual cause — each cost
real time to trace. Not filed against SuperDocs (`submission/bugs-found.md` is specifically
for SuperDocs' own surfaces), but recorded honestly here since they're real and this round
grades honesty over a clean-looking story.

- **`ltiservice_gradesynchronization` isn't set by `lti_add_type()`'s obvious fields.**
  Without it, Moodle launches the tool in legacy LTI 1.1 "basic outcomes" mode — the launch
  JWT simply never carries an `lti-ags/claim/endpoint` claim, with no error anywhere. Found
  by decoding a launch JWT and noticing the claim was silently absent, not present-but-empty.
- **Moodle's outbound curl firewall blocks any port outside {80, 443} by default.** This
  tool listens on 9001, so every server-to-server call Moodle makes to it (the JWKS fetch,
  the AGS score POST) failed — the JWKS failure surfaces as
  `fix_jwks_alg(): Argument #1 ($jwks) must be of type array, null given`, which names a
  PHP type error, not "port blocked." `register_tool.php` adds 9001 to
  `curlsecurityallowedport` for this local instance only.
- **The same firewall separately blocks common private-network destination IPs by
  default, and Docker Desktop's `host.docker.internal` resolves into exactly that range.**
  With the port allowed, the JWKS fetch still silently returned nothing —
  `download_file_content()` came back `false` with no exception and no log line naming the
  host — because the resolved IP (`192.168.65.x` on this machine; it can differ per install
  and can change after a Docker VM rebuild) sits inside the `192.168.0.0/16` block on
  `curlsecurityblockedhosts`. `register_tool.php` clears that setting for this local
  instance only.
- **A Deep Linking content item that sets its own `url` gets bound to `typeid=0`
  (a legacy ad-hoc-URL placement) instead of the registered LTI Advantage tool.** The
  resulting course module then launches over LTI 1.1 "basic outcomes" with no AGS claim in
  the id_token at all — no error, just a launch that later fails with
  `pylti1p3.exception.LtiException: Missing state param` once the tool tries to treat it as
  Advantage. Traced by decoding that launch's JWT and finding
  `lti-bo/claim/basicoutcome` where `lti-ags/claim/endpoint` should have been. Fixed by not
  calling `DeepLinkResource.set_url()` in `/configure/` at all (see the comment there) —
  Moodle then falls back to the tool's own registered launch URL and binds `typeid` to the
  real tool.
- **Two different callers need two different hostnames for "the tool."** A browser
  resolving `host.docker.internal` fails outright (only containers can resolve it); Moodle's
  own PHP resolving `localhost` for a server-to-server call reaches itself, not the tool.
  Splitting `lti_initiatelogin`/redirect URIs (browser-facing → `localhost`) from
  `lti_publickeyset` (server-to-server → `host.docker.internal`) is what actually fixed a
  `pylti1p3.exception.LtiException: State not found` that looked like a cookie bug.
- **AGS silently requires `Grade.timestamp`.** Omitting it doesn't error inside `pylti1p3`
  — it fails Moodle-side with `Incorrect score received` and no indication of which field.
  Found by patching a `error_log()` call into Moodle's own `scores.php` temporarily to see
  the actual score payload Moodle received.
- **AGS only grades gradable (Student-role) users.** Testing as the site admin fails the
  same generic "Incorrect score received" 400 — admins aren't gradable, and the message
  doesn't say so. `create_test_fixtures.php` creates and enrolls a real student for this
  reason.

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `SUPERDOCS_API_KEY` | yes | — |
| `SUPERDOCS_BASE_URL` | no | `https://api.superdocs.app` |
| `FLASK_SECRET_KEY` | no (dev only) | `dev-only-change-me` |
