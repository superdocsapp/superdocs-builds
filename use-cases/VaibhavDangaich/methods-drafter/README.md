# methods-drafter

Turns a **Methods Register** — the deliverable my `doctask` project produces from a pile of
lab records (a separate, private repository for this hiring round) — into an actual drafted
Methods section for a paper, using SuperDocs' chat API to write it and its export API to
hand back a real `.docx`.

## What it does

doctask reads a folder of lab notebooks/protocols and produces a register: every
experimental parameter the record states (with the exact quote and file it came from), and
every parameter a paper would need that the record does **not** state, listed as a gap
rather than guessed at. That's structured JSON — useful for a machine, not something you'd
hand a co-author.

`methods_drafter.py` takes that JSON and asks SuperDocs to write the actual prose: a
Methods section a human would recognize, exported to `.docx` and `.md`. Two rules carry over
from the register unchanged, on purpose:

- **A gap stays a gap.** If a parameter wasn't reported, the draft says so as a stated
  limitation ("the polymerase lot number was not recorded") — it never invents a
  plausible-sounding value to fill the hole.
- **A conflict stays visible.** If two source documents disagree on the same parameter (this
  happens in the bundled example — two notebook entries give different annealing
  temperatures), the draft states both values and which document said which, instead of
  silently picking one.

Softening either of those in the handoff to SuperDocs would throw away exactly the work
doctask did to establish them.

## What SuperDocs features it uses

- **`POST /v1/chat/async`** — drafts the section from scratch (a document-scale generation,
  so async rather than sync per the API's own guidance)
- **`GET /v1/jobs/{job_id}`** — polled until the draft completes
- **`POST /v1/documents/export`** — renders the finished session as `.docx` and `.md`

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # then edit .env with your real SUPERDOCS_API_KEY
set -a && source .env && set +a
.venv/bin/python methods_drafter.py --register example_register.json --out methods_qpcr
```

`example_register.json` is a real register — a real `GET /corpora/qpcr/register` response
from a running doctask instance, not hand-written. `example_output/` holds a real,
unedited run's output (`methods_qpcr.docx`, `methods_qpcr.md`) so you can see the result
without spending your own quota first.

Point `--register` at your own doctask corpus's register export to draft from your own
data:

```bash
curl http://localhost:8090/corpora/<your-corpus>/register > my_register.json
.venv/bin/python methods_drafter.py --register my_register.json --out my_methods
```

## Idempotency

Drafting is the billable step. A repeat run with an unchanged register (hashed by content,
not filename) reuses the prior SuperDocs session and only re-exports — it does not redraft
and does not re-bill. Pass `--force` to draft again anyway. State lives in
`.methods_drafter_state.json` (gitignored — it's a local run cache, not something to ship).

## Error handling

Both failure modes you're likely to hit locally are named with their fix, not just the raw
error:

```
$ python methods_drafter.py --register example_register.json
SUPERDOCS_API_KEY is not set. Fix: export SUPERDOCS_API_KEY=sk_... (get one at
https://docs.superdocs.app/account/mcp-setup, or reuse the key from your existing
SuperDocs account).

$ python methods_drafter.py --register does_not_exist.json
error: register file not found: does_not_exist.json. Fix: pass --register pointing at a
doctask register export (GET /corpora/{id}/register), or use the bundled
example_register.json.
```

Any SuperDocs API error (bad key, quota exhausted, a failed job) surfaces the API's own
`detail` message rather than a bare status code.

## A rough edge found while building this

`POST /v1/documents/export`'s own OpenAPI description says binary formats come back as a
JSON envelope with a `download_url` — that's true for an MCP tool call, but calling the
same endpoint over plain REST (what this script does) returns the rendered file directly in
the response body instead, no envelope. Cost about ten minutes to a `JSONDecodeError`
before I checked the raw response by hand instead of trusting the description; `export()`
in `methods_drafter.py` now branches on the actual `content-type` header rather than
assuming a shape. Reported in the parent round's `bugs-found.md`, Batch B.

## Environment variables

| Variable | Required | Default |
|---|---|---|
| `SUPERDOCS_API_KEY` | yes | — |
| `SUPERDOCS_BASE_URL` | no | `https://api.superdocs.app` |
