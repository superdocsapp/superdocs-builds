# PROGRESS.md

Running log of decisions, assumptions and live API calls. Append-only; nothing is rewritten
after the fact.

---

## 2026-08-10 — Phase 0: ground truth and skeleton

### Done

- Located the published specification: **`openapi.json` at the root of
  `github.com/superdocsapp/docs`** — OpenAPI 3.1.0, "Universal Document AI API" v2.0.0,
  77 paths, 66 schemas. Vendored to `spec/openapi.json`, pinned to commit `ac0d44c`
  (2026-07-24), SHA-256 recorded in `spec/PINNED.md`.
- Wrote `docs/behaviours.md`: **102 behaviours**, each with a source citation and a transport
  tag. This is the specification of the mock and the index of the contract suite.
- Skeleton, packaging, `.gitignore`, `TASK.md`, this file.
- Verified the API key works: `GET /v1/agents/whoami` → `200` in 0.89 s. **Non-billable.**

### Live calls this session

| # | Call | Billable | Result |
|---|---|---|---|
| 1 | `GET /v1/agents/whoami` | no | `200` · tier `free` · quota 500, used 0 |
| 2 | `GET /v1/users/me/promotions` | no | `200` · 1 active: 10,000 ops granted, 10,000 remaining, expires 2026-09-09 |
| 3 | `GET /v1/users/me/usage` | no | `401` — web-app sessions only, as documented (confirms B-005) |

**Operations spent: 0 of the Phase 1 budget of 50.**

### Findings raised

- **F-001 (confirmed live)** — `whoami` reports the tier bucket only and omits active
  promotional operations. This account reads as `remaining: 500` while actually holding
  10,500. The docs point agents at exactly this call to budget long jobs, so the guidance and
  the response disagree. Written up in `docs/findings.md`.
- **F-002 (VERIFY)** — the export `200`: `/concepts/documents` describes a binary download,
  `openapi.json` declares `application/json`. Settle in Phase 1.
- **F-003 (VERIFY)** — supported upload formats contradict between `/concepts/documents`
  (lists DOC and ODT) and `/errors/error-codes` (says `.doc` is a `415`, ODT unlisted).
  Settle in Phase 1.

### Decisions

- **Starlette, not FastAPI.** Startup time is graded by the card. Request-time validation is
  not needed for a replay server; validation belongs in the contract suite where a reviewer
  can see it. The measured comparison goes in the README rather than being asserted.
- **One process, one port, both transports.** Live serves REST at `/v1/*` and MCP at `/mcp/`
  on the same origin with the same bearer token, so the mock does too. An integrator changes
  one base URL and both halves of their stack redirect.
- **The MCP tool surface gets its own pin**, captured in Phase 1, because it is served live
  from the backend and can therefore move with no release anywhere. It is the most
  drift-prone artifact in the project.
- **Cassettes recorded, not hand-written.** Hand-written fixtures encode what I believe the
  API does; recorded ones encode what it did.
- Distribution: **GHCR + GitHub Release**. No PyPI — not worth claiming a namespace mid-round.
- MCP is a **floor deliverable**, not a stretch (decision taken with the user, 2026-08-10).

### Assumptions logged

- The pinned spec commit `ac0d44c` is the current tip of the docs repository's default branch
  as of 2026-08-10. If SuperDocs pushes a spec change during the round, the Phase 6 watcher
  catches it; until then this pin is the contract.
- `openapi.json` is treated as authoritative for **shapes**, and the prose docs as
  authoritative for **behaviours**. Where they conflict, the live service decides and the
  conflict is recorded as a finding.
- The 38-tool / 4-prompt MCP surface is taken from the docs and will be asserted against the
  live handshake in Phase 1. A mismatch is a finding, not a correction to make quietly.

### Next

Phase 1 — author the fabricated corpus, pin the MCP surface, build the recorder, capture the
six scenarios. Requires the API key; budget 50 operations.

---

## 2026-08-10 — Phase 1: corpus, recorder, cassettes

### Done

- **MCP surface pinned.** Live handshake against `https://api.superdocs.app/mcp/` →
  `spec/mcp-tools.json`. **38 tools, 4 prompts, `instructions` present**, protocol
  `2025-06-18`, server `SuperDocs 3.4.0` — matching the documentation exactly (B-095,
  B-096 confirmed). `scripts/pin_mcp_surface.py --check` is the drift watcher's engine.
- **Corpus authored before any recording**, all fabricated: a 42 KB styled Master Services
  Agreement (32 numbered clauses, two tables with merged header cells and alternating
  shading, running header and footer with a PAGE field, A4 geometry), a Markdown operations
  review, a 400-section register, a 25,600-section register, a `.doc` probe and an `.odt`
  probe. Deterministic — rebuilding produces byte-identical files, verified by digest.
- **Recorder built** (`src/sdmock/record.py`): performs live calls, captures SSE frame by
  frame with arrival offsets and sequence numbers, speaks MCP JSON-RPC over Streamable
  HTTP, scrubs on write, and enforces a hard operation budget.
- **10 cassettes** committed (target was 8): 7 recorded, 3 synthesised and labelled.
- **Fixture-secrecy gate** (`contract/test_fixtures_are_clean.py`): 43 tests, no key, no
  network. Asserts no cassette carries a credential, that each is canonically serialised
  and self-describing, and that a synthesised cassette can never pass as a recording.

### Live calls this session

**Operations spent: 27 of the 50 budget** (verified against `/v1/users/me/promotions`:
10,000 → 9,973). Breakdown: 2 on the two review recordings, 16 on the first large-edit
attempt, 9 on the second. Everything else — uploads, exports, parses, MCP handshakes,
`whoami`, `get_account_status` — was free, as documented (B-089).

### Findings raised

Six now, five confirmed live, in `docs/findings.md`. Two are worth calling out:

- **F-004 (high)** — `POST /v1/documents/upload` returns neither `status` nor `parse_mode`,
  both of which `ProcessDocumentResponse` declares **required**, and adds three fields the
  schema does not describe. A client generated from the published spec fails validation on
  every successful upload. This is the exact failure this project exists to catch, and it
  was caught on the first recorded call.
- **F-006 (high)** — SSE `sequence` is not strictly increasing: an `intermediate` and the
  `final` were both emitted as `11`. A client that follows the documented resume advice —
  store the highest sequence, reconnect with `last_sequence` — never receives `final` after
  a dropped connection, and waits forever for a job that has already completed.

F-002 and F-003 are now settled: the export `200` is a genuine binary DOCX (the spec's
`application/json` is wrong), and `.odt` uploads succeed while `.doc` returns a `400`
rather than the documented `415`.

### Decisions

- **Three cassettes are synthesised, not recorded, and say so.** `rate-limit` would cost
  the account's entire 10,500-operation balance to observe. `rate-limit-surge` is emitted
  by the platform edge under load and cannot be induced by one caller at all. The only
  other route to a real `429` is the limit-increase cooldown, which emails the SuperDocs
  team on every call — hammering a founder's inbox to record a fixture is worse than
  reconstructing one. Each carries a `synthesis_note` explaining why, the mock surfaces the
  flag, and the contract suite skips them against the live target.
- **`paused-large-edit` is synthesised too, after a genuine attempt.** A real 400-section
  whole-document edit (16 operations) completed in one turn without pausing — the
  continue-prompt threshold sits above 400, and the docs' own example is 864. Chasing it
  would have consumed most of the remaining budget on a maybe. The real edit is kept as
  `large-multi-section-edit`, which turned out to be worth having on its own: compact mode,
  `updated_html: null`, 224 `chunk_diffs`, and the summary "224 sections edited, rest
  untouched".
- **Session ids are fixed strings**, so a re-recording lands on the same paths and the
  cassette diffs only where behaviour moved.
- **Polls are recorded selectively** — the state transitions, not two hundred identical
  `in_progress` rows.

### Bugs found in my own code, and fixed

- The recorder died on `RemoteProtocolError: Server disconnected without sending a
  response` while polling a long job, losing a recording that had already cost 16
  operations. Transport-level failures are now retried with backoff, and only on
  idempotent methods, so a dropped response can never become a double charge.
- The budget counter triple-counted: a completed job repeats its `usage` block on every
  poll, and the counter charged it each time — it read 27 for 9 operations actually spent.
  Charges are now keyed by job id and counted once.
- The scrubber redacted `hello@superdocs.app` out of the capacity-refusal body. That is
  SuperDocs' own public support address, and it is the address the error tells integrators
  to write to; redacting it made the fixture less useful and no safer.

### Assumptions logged

- `.tex` appears in the live `supported_formats` list and in no documentation page. Not
  probed — it costs nothing to leave alone, and the finding stands on `.doc` and `.odt`.
- The continue-prompt threshold is somewhere above 400 sections. Not bisected: each probe
  costs roughly one operation per 25 sections, and knowing the exact number changes nothing
  about the fixture.

### Next

Phase 2 — the replay server: REST at `/v1/*` and MCP at `/mcp/` on one port, scenario
switching by header, deterministic responses, real SSE framing with `last_sequence` resume.
No API key needed.

---

## 2026-08-10 — Phase 2: the replay server, both transports

**No operations spent.** Still 27 of 50; nothing in this phase touches the live service.

### Done

- **The spec does real work at runtime.** `src/sdmock/spec.py` builds the route table and a
  path matcher out of the pinned `openapi.json` (81 routes). This is what makes the
  cassettes portable: a recording captured against `sdmock-review-001` replays for a client
  using `tenant_9.prod`, because both normalise to the spec's own
  `/v1/chat/{session_id}/approve`. Without it the mock would only work for whoever recorded
  it.
- **Replay core** (`replay.py`): interactions keyed by (method, template), ordered cursors
  per (scenario, run). The cursor walking a recorded sequence *is* the job state machine —
  `in_progress` → `awaiting_approval` → `completed` is data, not code.
- **REST app** (`app.py`): one catch-all rather than a hand-written route table, auth
  emulation, `X-Mock-Scenario` / `X-Mock-Run` / `X-Mock-Latency`, SSE with `last_sequence`
  resume, `/__sdmock__/catalogue` and `/__sdmock__/reset`.
- **MCP server** (`mcp/server.py`) at `/mcp/` on the **same port**, mirroring live.
  `initialize` / `tools/list` / `prompts/list` answer from the Phase 1 pin — all 38 tools
  and 4 prompts, not a retyped subset. `tools/call` serves an MCP recording verbatim when
  one exists and otherwise resolves through the **same** `Library` the REST app uses, so
  the two transports cannot drift apart.
- **In-process harness** (`testing.py`): `MockServer` on a real port and socket, because a
  transport shim hides exactly the failures a mock exists to catch.
- **80 tests**, all with no key and no network.

### Measured

Cold **process** start → first accepted connection, N=10, this machine:
**median 138 ms, p95 141 ms, max 367 ms.** The card asks for under a second. The formal
harness with committed raw data lands in Phase 5; this is the preliminary number.

### Bugs found in my own code, and fixed

- **SSE resume was wrong, and wrong in the direction that hides itself.** Resuming from
  `last_sequence=2` returned *more* frames than the full stream, because the cursor was
  handing out the second recorded stream rather than filtering one event history. A stream
  is not a sequence of responses — it is one event history a client may attach to more than
  once. Now merged, deduplicated on (event, data), and filtered by sequence.
- **A real `account_id` reached a committed cassette.** MCP tool results carry their payload
  as text, so key-based redaction walked straight past it. Worse, the audit could not have
  caught it either: on disk the inner quotes are backslash-escaped and the pattern missed
  them. Fixed in three places — the scrubber now redacts nested identifiers in place
  (without re-serialising, so the double-encoded payload keeps its exact bytes), the audit
  checks the unescaped form too, and `contract/test_scrubber_has_teeth.py` now proves the
  gate rejects eight specific payloads including that exact one.
- The strengthened audit immediately found a second leak the old one had passed: a
  `redemption_id` in the review cassette. Fixed with `scripts/rescrub_cassettes.py` rather
  than by re-recording — the scrubber is deterministic and edits in place, so re-scrubbing
  produces exactly what recording again would have, without spending someone's quota to fix
  a bug in this repository.
- `large-multi-section-edit` claimed to cover the continue-prompt behaviours it never
  observed. Corrected in both the cassette metadata and the recorder.

### Decisions

- **A missing recording returns `501` and says which scenario has it.** The alternative —
  synthesising a plausible body from the spec — is worse than useless: a test would encode
  the invention as truth. Honestly absent beats present and broken.
- **Auth is required by default but any bearer value is accepted.** Demanding a real key
  would defeat the point; accepting a *missing* header would stop the mock catching a
  client that forgot to send one. `SDMOCK_REQUIRE_AUTH=false` opts out.
- **The mock reproduces F-006 rather than tidying it away**, and a test asserts the failure
  mode still reproduces. An integrator can now regression-test their workaround for the
  duplicate-sequence bug against a fixture instead of against production.
- **The handshake says `SuperDocs (sdmock replay)`.** A mock should never be able to
  impersonate the service it stands in for, and a test asserts it.

### Next

Phase 3 — the contract suite: schema conformance against the pinned spec, tool-surface
conformance against the pin, the behaviour ledger asserted by B-ID, the four-call journey,
and REST/MCP parity. Runs against `--target mock` free, and `--target live` under a budget
guard.

---

## 2026-08-10 — Phase 3: the contract suite

**Operations spent this phase: 1.** Total across the whole build: **29 of the 50 budget**
(promo balance 10,000 → 9,971, measured, not inferred).

### Done

One suite, four combinations, identical assertions — `{rest, mcp} × {mock, live}`. All four
green:

| Run | Result |
|---|---|
| `pytest` (mock, REST, no key) | 147 passed |
| `pytest --transport mcp` (mock, MCP, no key) | passed |
| `pytest --target live` (REST) | **120 passed, 27 skipped, 0 failed** |
| `pytest --target live --transport mcp` | **98 passed, 49 skipped, 0 failed** |

Dated evidence for both live runs is committed under `docs/evidence/`, written by the suite
itself rather than typed into a report.

Five layers: schema conformance against the pinned spec; MCP tool-surface conformance
against the pin; the behaviour ledger asserted by `B-ID`; the four-call journey; and
REST↔MCP parity — which is only meaningful because both transports resolve through one
replay core, so it tests the service rather than my copy-paste.

**The coverage gate is wired into CI**: 110 ledger rows — **67 asserted by a test, 23
exercised by a recorded fixture, 21 excused in writing, 0 uncovered.** The three tiers are
tracked separately because they are different strengths, and calling a fixture an assertion
would be the kind of number-inflation this project is supposed to be the antidote to.

### The correction that mattered

**F-004 was wrong and has been retracted.** I claimed `POST /v1/documents/upload` violates
`ProcessDocumentResponse` by omitting two required fields, and rated it high severity. The
upload route does not reference that schema at all — its `200` schema is `{}`. Driving the
route that *does* reference it, `POST /v1/uploads/{upload_id}/process`, end to end through
the pre-signed upload flow showed it **conforms exactly**: `status: "completed"`,
`parse_mode: "document"`, every declared field present.

I had matched a schema to a route on the strength of its field names. The retraction is
left visible in `docs/findings.md` rather than edited away, and what survives is a real but
much smaller finding: the two multipart upload routes publish no response shape at all.

That episode is also why `KNOWN_DRIFT` is now empty and says so. Every response this suite
has observed validates against the schema its route publishes.

### Bugs found in my own code, and fixed

- **`_prune` was destroying evidence.** It recursively dropped every empty list and object
  on the way to disk, including inside recorded response bodies. `GET /v1/users/me/promotions`
  returns `{"active": [...], "history": []}`; the empty `history` was deleted, and the schema
  check then reported a required property missing — a finding against SuperDocs that was
  entirely my serialiser's doing. Pruning is now confined to the format's own wrapper fields.
  Fixtures are evidence, and tidying evidence is how you report your own bugs as someone
  else's.
- **Matching on (method, path) alone could not tell two recordings apart.** The export
  cassette holds a `200` and a `422`, and a caller sending an invalid format got whichever
  the cursor happened to be on. Candidates are now scored on how well the incoming body
  matches the recorded one, with cursor order as the tie-break.
- **The budget counter under-reported.** It counts from `usage` blocks, and a review job
  left paused reports nothing until it completes — so a run that spent an operation read
  zero. The suite now measures the balance directly before and after a live run and prints
  both numbers, the inferred one because it is what the in-run guard enforces and the
  measured one because it is the truth.
- Two live-only test-setup bugs, both mine: exporting from a fresh live session (which holds
  no document) and asserting parity against a cassette's job id (which does not exist live).

### Found while fixing those

`B-111` — exporting from a session that holds no document returns `404` with *"No document
loaded in this session. Load a document first, then export."* An actionable message rather
than an empty file, and one of the first errors an integrator meets while wiring up the
four-call contract. Now recorded and asserted.

Also confirmed: an abandoned review job costs nothing. The live parity test starts a real
review and leaves it paused, and the balance does not move — which is B-090 holding.

### Next

Phase 4 — the mutation kill-matrix: boot the mock with deliberate, documented defects and
prove the suite fails on each one. A suite that has never been seen to reject anything is
decoration.

---

## 2026-08-10 — Phase 4: proving the suite has teeth

**No operations spent.** Still 29 of 50. The whole matrix runs against the local mock.

### Done

`src/sdmock/mutants.py` holds **18 deliberate defects**, each violating exactly one
documented behaviour, each naming the ledger row it breaks and why the defect would matter
to somebody. `SDMOCK_MUTANT=M6 sdmock serve` boots the mock broken in exactly that one way.

`scripts/run_kill_matrix.py` boots the mock under each mutant in turn, runs the contract
suite unchanged, and records which test caught it. **18 of 18 killed**, in 69 seconds, with
no key. The result is committed as `docs/kill-matrix.md`, generated rather than written.

This is the artifact that answers the card's "the contract suite genuinely catches a drift".
A passing suite proves nothing on its own — it might be asserting real invariants or it
might be asserting that `200 == 200`, and from the outside those look identical. Breaking
the mock on purpose is the only way to tell them apart, and it does not depend on SuperDocs
happening to ship a breaking change during the round.

### Two survivors on the first run, and they were different problems

The first run killed 16 of 18. Both survivors were worth having.

- **M15 was a genuine hole in the suite.** Nothing asserted that compact response mode
  actually suppresses `updated_html` — B-016 was checked as a claim about the spec's prose,
  not about a response. So a mutant that ignored compact mode passed the entire suite. That
  is a silent cost regression in production: nothing errors, an agent's context bill just
  doubles. Fixed by writing `test_compact_mode_suppresses_the_full_document`, which asserts
  `updated_html is None` and that `chunk_diffs` arrive in its place.

- **M11 was a bug in my mutant plumbing.** The defect was "ignore `last_sequence` and replay
  everything", but the app filtered the frames *before* handing them to the mutant hook, so
  the mutant was a no-op and survived by doing nothing. The hook now receives the unfiltered
  history plus the requested cursor, and the mutants that break something else filter for
  themselves.

The second is worth naming plainly: **the mutants need to be falsifiable too.** A mutant
that cannot express its defect is a false negative dressed as a passing grade, and it would
have quietly inflated the kill rate. It was caught because a survivor is treated as a
finding rather than as noise.

### Decisions

- **The full matrix does not run in the default `pytest`.** Seventy seconds belongs in CI,
  not in every invocation. What runs by default is the part that rots: every mutant is
  documented, every mutant cites a real ledger row, the committed matrix covers every
  mutant, and it records no survivor. The full run is `--check` in CI (Phase 6).
- **Mutation is opt-in and asserted to be off.** A test fails if `SDMOCK_MUTANT` is set
  during a normal run, so a broken mock can never be mistaken for a faithful one.
- **A survivor is fixed by writing the missing assertion, never by weakening the mutant.**
  Written into the script's own failure message so the temptation is at least on record.

### Next

Phase 5 — container, library, generated scenario catalogue, and the startup benchmark with
committed raw data.

---

## 2026-08-10 — Phase 5: container, library, catalogue, benchmark

**No operations spent.** Still 29 of 50.

### Done

- **Container**: multi-stage, `python:3.12-slim`, non-root (uid 10001), `HEALTHCHECK`,
  **47 MB**, both transports on one port. Built and driven end to end — upload, MCP
  `tools/list`, a binary DOCX export, and a `401` for a missing bearer. `docker run` to
  first `200 /health` is roughly **500 ms** over five runs, Docker's own container-creation
  overhead included.
- **Library**: `pip install sdmock` now gives a working mock with **no repository
  checkout** — the fixtures ship inside the wheel. The `superdocs_mock` pytest fixture is
  registered through the `pytest11` entry point, so installing the package is the whole
  setup, with no conftest entry. Verified by installing into a clean venv in a temporary
  directory and running a stranger's test file against it: both transports, 2 passed.
- **Scenario catalogue**: `docs/scenarios.md`, generated from the cassettes, with a CI test
  that fails when it is stale. A hand-written catalogue is a second source of truth that
  starts drifting the first time a scenario is re-recorded, and drifts silently.
- **Startup benchmark**: method written before the numbers, N=20, raw per-run samples in
  `docs/benchmarks/startup.csv`.
- **`scripts/fresh_clone.sh`**: copies the tree to a clean directory, builds a venv, runs
  the suite with no key, starts the server and walks the four-call contract over both
  transports. "A stranger can go from clone to working" is a claim like any other, so it is
  tested rather than hoped.
- **README** rewritten around the evidence rather than the feature list.

### Measured

| Measurement | median | p95 | max |
|---|---|---|---|
| process start → socket accepts | 156 ms | 185 ms | 234 ms |
| process start → `200 /health` | 157 ms | 186 ms | 240 ms |
| process start → MCP `tools/list` | 160 ms | 188 ms | 242 ms |
| `docker run` → `200 /health` (N=5) | ~500 ms | — | 607 ms |

The card asks for under a second. Met on every one of the twenty runs, with the container
path — which is the one CI actually uses — met too.

**On D1, the Starlette-over-FastAPI decision, now substantiated rather than asserted:**
FastAPI costs **195 ms** to import against Starlette's **75 ms** here. That is a real
difference, but the honest reading is that Starlette bought headroom rather than saved the
bar — FastAPI would still have cleared a second. The decision holds because the mock does
not need request-time validation, not because it was forced. Written up that way in the
README rather than dressed up as a narrow escape.

### Bug found in my own code, and fixed

The container built and then could not find its own fixtures. Every data path was resolved
relative to the source tree, which is true in a checkout and false in an installed wheel and
false again in an image. Introduced `sdmock/paths.py` with explicit ordered resolution — an
environment variable, then the packaged copy inside the wheel, then the checkout — and made
the wheel carry `spec/` and `cassettes/` via `force-include`. The container sets
`SDMOCK_CASSETTES` and `SDMOCK_SPEC` at `/app`, so an integrator can mount their own
recordings over the baked-in ones.

Worth naming because it is the class of bug that only appears at the moment someone else
tries to use the thing: it passed every test, ran perfectly from the checkout, and was
broken in both of the two forms the card actually asks for.

### Next

Phase 6 — CI, the spec and tool-surface drift watchers, and hardening. Then Phase 7,
the pull request.

---

## 2026-08-10 — Phase 6: CI, drift watchers, hardening

**No operations spent.** Still 29 of 50.

### Done

- **`ci.yml`** — everything checkable without a key, on every push: the contract suite
  across {rest, mcp} × {py3.10, py3.12}, the kill matrix with `--check` plus a
  `git diff --exit-code` so the committed matrix cannot go stale, the generated-docs
  checks, gitleaks over full history, `fresh_clone.sh`, and a container build that is
  then driven on both transports.
- **`live.yml`** — the contract suite against `api.superdocs.app`, weekly and on manual
  dispatch only, never on push, with billing behind an input and a hard operation budget.
  It uploads the dated evidence file.
- **`watch-surface.yml`** — daily. Diffs the published `openapi.json` and the live MCP
  `tools/list` against the pins and opens an issue naming exactly what moved.
- **`scripts/watch_surface.py`** — run for real, not just written: reports *unchanged*
  today, and `test_the_drift_watcher_can_actually_see_drift` proves it detects a removed
  route, an added route and a retyped schema field. A watcher never seen detecting
  anything is a cron entry.
- **`contract/test_hardening.py`** — the properties that decide whether this is
  trustworthy in someone else's CI: no credential in the mock's logs or echoed in a
  response, record mode refusing without a key in a message that names the fix, an
  unreachable upstream failing loudly, 16 threads hammering one scenario without
  corruption, replay idempotent over 20 repeats, and the mock unable to be quietly
  running a mutant.

### The mistake gitleaks caught

**I had used the real API key as a fixture in the leak test.** `test_scrubber_has_teeth.py`
needs payloads that look like genuine credentials, and I reached for the one in front of
me. gitleaks found it in the history of the Phase 2 commit.

Fixed three ways: the fixture is now an obviously synthetic value that still matches the
shape the scrubber hunts for; the string was purged from every commit with
`git filter-branch` (the repository has never been pushed, so nothing downstream is
affected); and the scan now passes over the full rewritten history.

**And the config does not paper over it.** It would have been easy to allowlist
`contract/` or `cassettes/` wholesale and move on. That is exactly backwards — a recorded
fixture and a leak test are the two places a real credential is *most* likely to land,
because in both a credential looks like it belongs. Every exemption in `.gitleaks.toml`
names one literal value, and the reasoning is written above it.

**Separately: the key should be rotated.** It has appeared in a shell session and in this
project's working history, and rotation costs nothing.

### Recorded, not reported as a bug

**N-1** — a hardening test caught an api_key in a log line, and the culprit was the *test
client*, not the mock: httpx logs every request URL at INFO, and SSE authenticates by
query parameter because `EventSource` cannot send headers. Nothing is behaving incorrectly,
so it is filed as an observation rather than a defect — but the consequence is easy to
miss, and it is worth SuperDocs naming the hazard in `/guides/streaming`: a key used for
browser-side streaming lands in client logs, proxy logs and browser history by
construction, and should be treated as more exposed than a server-side one.

### Next

Phase 7 — the pull request into `superdocs-builds`, the README screenshot, and the
findings email.
