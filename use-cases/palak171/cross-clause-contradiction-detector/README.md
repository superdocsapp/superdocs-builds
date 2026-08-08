# Cross-clause contradiction detector

**Who it serves:** Legal and compliance.
**What it builds:** Finds places where one clause of a contract contradicts
another, explains the conflict, and proposes a resolution as a reviewable
edit — built entirely on the SuperDocs API. SuperDocs' own AI does every
edit; this tool only shapes the prompts and drives the Review workflow.

## Why two passes, not one

The card's whole test is precision: *"it finds genuine contradictions in a
real contract and does not flag ordinary tension as conflict."* One giant
"find and fix everything" prompt makes that hard to inspect. This tool splits
it into two passes across the three surfaces the card names:

1. **`detect`** (chat/search surface) — read-only. Uploads the contract and
   asks SuperDocs to report genuine contradictions only, explicitly
   instructed to skip clauses that merely relate without conflicting. No
   edit is made in this pass, so a wrong detection costs nothing to undo —
   you just don't run `resolve`.
2. **`resolve`** (Review/HITL surface) — proposes one edit per contradiction
   named in the detect pass, via `POST /v1/chat/async` with
   `approval_mode: "ask_every_time"`. Every proposed edit is approved or
   rejected **individually** through `/v1/chat/{session_id}/approve` —
   rejecting one never discards the others (see
   `tests/test_contradiction_detector.py::test_resolve_applies_mixed_approve_reject_decisions_and_exports`,
   which asserts exactly that with one approved and one rejected edit in the
   same batch).

`run` does both in sequence for convenience.

## The sample contract is a precision test, not just a demo

`sample_contracts/vendor_services_agreement.txt` is synthetic and contains
**one genuine contradiction and one deliberate near-miss**, on purpose:

- **Genuine contradiction** — Clause 18 says either party may decline to
  renew with **60 days'** notice; Clause 20 says, "Notwithstanding Clause
  18," **30 days'** notice. Same obligation, same trigger, two different
  numbers with no distinguishing condition. This should be flagged.
- **Near-miss (should NOT be flagged)** — Clause 7 gives **undisputed**
  invoices a 30-day payment term; Clause 12 gives invoices **disputed in
  good faith** a 45-day term measured from dispute resolution. These look
  similar (both about invoice payment timing) but govern mutually exclusive
  cases — this is a carve-out, not a conflict. A strong detector says so; a
  weak one flags it anyway.

Run `detect` against this file and check which way it goes on Clause 7 vs 12
— that result is the single most informative thing to include in the
write-up and demo video.

**Already run against the live API — see [`LIVE_VERIFICATION.md`](LIVE_VERIFICATION.md):**
the default model tier (`core`) missed the genuine contradiction entirely;
`--model-tier max --thinking-depth deep` caught it correctly and still left
the Clause 7/12 near-miss alone. The Review pass then resolved it, and the
exported `.docx` was verified to actually contain the fix. A real bug was
found and fixed along the way (a Windows console encoding crash), documented
there as well.

## Setup

```bash
pip install -e ".[dev]"
cp .env.example .env   # then fill in SUPERDOCS_API_KEY
```

Get a key: sign up at [use.superdocs.app](https://use.superdocs.app), redeem
`BUILDER26` (Settings → Billing) for 10,000 free operations, then
Settings → API Keys → Create API Key.

## Run it

```bash
python contradiction_detector.py run sample_contracts/vendor_services_agreement.txt \
  --export reviewed_contract.docx
```

This uploads the contract, prints the contradiction report, then walks you
through approving or rejecting each proposed edit one at a time (`y` /
`n` / type a reason to deny with feedback), and exports the final document.

Non-interactive modes for scripting or CI-style dry runs:

```bash
python contradiction_detector.py run contract.docx --auto-approve --export out.docx
python contradiction_detector.py run contract.docx --auto-deny   # report only, no edits committed
```

Or run the two phases separately:

```bash
python contradiction_detector.py detect contract.docx
# -> prints "Session id (pass to 'resolve'): contradiction-detector-ab12cd34"
python contradiction_detector.py resolve contradiction-detector-ab12cd34 --export out.docx
```

## Tests

```bash
pytest -v
```

12 tests, all against a mocked SuperDocs API (`respx`) — no live key, no
network call, no operations spent. They prove our request-building and
response-parsing (upload, chat, async job polling, mixed approve/reject
payloads, export header decoding, error handling) are correct. They do
**not** and cannot prove SuperDocs' own contradiction-finding accuracy —
that's what the demo video and the Clause 7-vs-12 result above are for.

## Why polling, not SSE

`POST /v1/chat/async` + `GET /v1/jobs/{id}` (polling) and the SSE stream are
two ways to reach the same HITL flow. We used polling: it needs one HTTP
client and no event-stream parsing, and — usefully for this exact task —
`job["metadata"]["pending_changes"]` from the polling path is already a
plain list, whereas the SSE path delivers it double-JSON-encoded
(`envelope.content` needs a second `json.loads`, per
`docs.superdocs.app/guides/streaming`). Polling sidesteps a footgun the task
brief explicitly warned about, at the cost of slightly higher latency
between an edit finishing and your code noticing — an acceptable trade for
a CLI tool with no UI needing live progress.

## Known limitations

- Detection accuracy depends on the underlying SuperDocs model tier
  (`--model-tier`/`--thinking-depth` flags are exposed; `max`/`deep` costs
  more operations but should catch subtler contradictions).
- The resolve prompt asks SuperDocs to prefer the clause with
  "notwithstanding"/"supersedes" language, falling back to the
  higher-numbered clause. This is a heuristic instruction to the AI, not
  code we control — a contract that contradicts itself with no textual
  signal of which clause wins will get *a* proposed resolution, but the
  human reviewer, not this tool, is the actual authority on which one is
  right. That's the point of the Review gate.
- No spreadsheet/table-cell-level contradiction detection — this build
  targets clause-level text contradictions in prose contracts.
