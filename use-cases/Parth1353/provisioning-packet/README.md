# Provisioning and Service-Order Packet

**One signed telecom order in. Twelve provisioning documents out. Kept in step
when the order changes.**

Built on SuperDocs by **Parth Saini** for the SuperDocs Round 2 engineer task
(assigned build: *Provisioning and Service-Order Packet*, band S2).

---

## The problem this solves

A service delivery manager gets a signed order for an enterprise circuit. Before
anything can be built they need six documents: the service order form, the site
survey request, the installation scope of work with an as-designed diagram, the
customer readiness checklist, the acceptance test plan, and the handover
certificate. They need them twice — once for the delivery team, once for the
customer, and the two must differ only in what the customer should not see.

Then, three weeks later, the customer upgrades from 1 Gbps to 10 Gbps and the
ready-for-service date moves. Now every one of those documents is wrong, in
different places, and the person who has to fix them is the same person running
four other installs.

That last paragraph is the whole reason this exists. Assembling twelve documents
once is a mail merge. Keeping twelve documents honest through six change orders
is the job.

## What it does

```bash
packet audit      # check the templates — offline, no API key needed
packet build      # one order record → 12 documents, in two SuperDocs sessions
packet change     # propagate a change, reviewing each edit before it applies
packet verify     # prove the packs say what the order says
packet export     # .docx and .pdf you can actually send
```

```
                       orders/acme-fiber-SO-40188.yaml
                          one record, ~60 declared fields
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
            internal pack (6)                   customer pack (6)
            everything                          internal blocks removed
                    │                                   │
                    └─────────────┬─────────────────────┘
                                  ▼
                       one SuperDocs session per pack
                                  │
   change ──► which documents carry this field? ──► one targeted edit each
                                  │
                          human reviews each proposed change
                                  │
                                  ▼
                          verify · export · send
```

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env      # add your SUPERDOCS_API_KEY
./demo.sh                 # the full walkthrough, ~26 operations
```

No key yet? Everything except the SuperDocs calls runs without one:

```bash
python -m packet audit            # template and audience checks
python -m packet build --dry-run  # renders all 12 documents locally, spends nothing
pytest -q                         # 49 tests, no key, no network
./demo.sh --dry-run               # the whole walkthrough, costing nothing
```

## What "strong" looks like on the card, and how each one is proved

### "Internal and customer packs differ only in what should be hidden"

Not a convention — a property of the data. Every field is declared once in
`packet/order.py` with an audience. `Order.value()` resolves an internal field
to a redaction when the caller is a customer document, so the check lives below
the templates rather than inside each of them. A template author who forgets to
wrap an internal field in a block gets a visible `[withheld — internal]`, not a
leaked margin.

**The evidence is committed**: [`samples/pack-difference.md`](samples/pack-difference.md)
is a diff of all twelve rendered documents. Every hunk is either the
INTERNAL banner or an `{{#internal}}` block. Nothing else differs.

Three tests keep it that way — one that no internal *value* appears anywhere in
the customer pack, one that every shared field renders identically in both, and
one that a planted leak is caught.

### "A date change updates every document that carries it"

The set of fields a document carries is **computed from its template**, so
"which documents does this change touch?" is derived, not maintained:

```
$ python -m packet audit --impact delivery.rfs_date --impact service.bandwidth_mbps

  delivery.rfs_date (Ready for service)
    internal pack: 6/6 — 01-service-order-form, 02-site-survey-request, …
  service.bandwidth_mbps (Bandwidth)
    internal pack: 5/6 — … (not the readiness checklist, which never mentions it)
```

Then each affected document gets **one targeted SuperDocs edit**, naming the old
and the new value exactly and forbidding anything else:

> Wherever the document says "16 February 2026" as the ready for service,
> replace it with "30 April 2026". There may be more than one occurrence; change
> all of them. […] Do not reword anything else. Do not change any other number,
> date, name or heading.

The alternative — re-render all twelve from the new record and re-upload — would
produce the same bytes and prove nothing. It is a rebuild wearing an update's
clothes, and it discards every edit anyone made to the pack in between.

### "The diagram reflects the ordered configuration"

The as-designed diagram is generated from the order record, never drawn.
Single-path and dual-path orders produce structurally different Mermaid; the
bandwidth appears on the links; the CPE model is in the node labels. SuperDocs
live-renders it in the editor and rasterises it on export, so it survives into
the customer's `.docx`.

It is regenerated **only** when the configuration actually moves —
`diagram_signature()` covers bandwidth, diversity, protection, handoff, CPE,
circuit and site labels, so a price change does not redraw the network.

The diagram also declares its own configuration in Mermaid comments
(`%% design:diversity=dual`) so `packet verify` can check the picture against
the order without guessing from prose. That is not decoration: the caption for a
single-path circuit reads *"no protection"*, and a substring check for
`protect` gets it exactly backwards. It did, in development, until the test
caught it.

## SuperDocs surfaces used

The four calls the brief names as the minimum contract, plus depth:

| | Where |
|---|---|
| **Upload** | `POST /v1/documents/upload` (multipart, `open_mode=new_focused`) — twelve documents into two sessions, chunk-ID parsed so later edits are surgical. Not base64: that endpoint *replaces* the focused document. |
| **Chat** | `POST /v1/chat/async` with `approval_mode: ask_every_time`, one targeted instruction per affected document, `model_tier: pro` |
| **Approve** | `POST /v1/chat/{session}/approve` — per-change decisions from a terminal review, with feedback on rejections |
| **Export** | `POST /v1/documents/export` — `.docx` and `.pdf`, A4, exporting the **live** body per document, with `X-Export-Warnings` read and surfaced |
| Multi-document | one session per pack, edits targeted by `document_id` |
| Diagrams | Mermaid, generated from the order and re-rendered on export |
| Free reads | `GET /v1/sessions/{id}/documents?include_html=true` for verification, `GET /v1/documents/{id}` structure for snapshots, `whoami` for the quota |

### REST or MCP

The assignment card says anything specified against the REST API may be built on
MCP and the other way around. This build uses REST, for one reason: the CLI is
the product here, and a CLI that speaks HTTP directly has no second process to
supervise and no transport to debug when a delivery manager runs it on a laptop.

The MCP surface reaches the same four calls, and is the better choice if you
want a coding agent driving the pack rather than a person:

```jsonc
// Claude Code, Cursor, VS Code, Windsurf
{
  "mcpServers": {
    "superdocs": {
      "url": "https://api.superdocs.app/mcp",
      "headers": { "Authorization": "Bearer $SUPERDOCS_API_KEY" }
    }
  }
}
```

```bash
claude mcp add --transport http superdocs https://api.superdocs.app/mcp \
  --header "Authorization: Bearer $SUPERDOCS_API_KEY"
```

With that connected, *"build the provisioning pack from
orders/acme-fiber-SO-40188.yaml, then move the RFS date to 30 April and show me
each change before it applies"* is one conversation. The parts that would not
come for free are the ones this repo actually contributes: the field registry
that makes the audience rule structural, the impact set computed from the
templates, and the verification that nothing else moved.

### Three things the docs warn about, handled once

* **`pending_changes` arrives JSON-encoded inside JSON.** `SuperDocs.pending_changes()`
  does the double parse in one place and is tested against both shapes. This is
  the documented reason integrators see diff cards where every field is
  `undefined`.
* **`awaiting_approval` means two different things.** A change review and a
  large-edit continue prompt share the status; calling the wrong endpoint returns
  409. Every path branches on `awaiting_kind` first.
* **Long operations look identical to crashes.** Polling has a generous ceiling
  and reports each status transition, so "still processing" is visible.

And one the brief mentions that shaped the CLI: **budget your operations.**
Every command takes `--dry-run` (prints the exact plan and its cost, makes no
billable call) and `--max-operations` (a stopping rule that refuses, not a
warning that logs).

```
$ python -m packet change --set service.bandwidth_mbps=10000 --dry-run
  Plan — 10 document(s) to edit, 2 left alone
  EDIT  internal/03-installation-scope-of-work   Bandwidth + regenerate diagram
  KEEP  internal/04-customer-readiness-checklist
  …
  10 billable operation(s) would be spent, one per document.
```

## Costs and latency, measured live

Against a real key on `model_tier: pro`, nine-document corpus, August 2026.

| | operations | elapsed |
|---|---|---|
| `packet build` (12 documents, 2 sessions) | 12 | ~30 s |
| A change touching every document | 12 | a few minutes |
| A change touching only the charges | 6 | ~1 min |
| The repair pass, when nothing was skipped | 0 | one free roster read |
| `packet verify` | 0 | seconds |
| `packet export` (all 12 files) | 0 | ~20 s |
| `packet audit`, any `--dry-run` | 0 | instant |

Per-call: ~2-3 s to upload a document, ~13 s for one `chat_async` edit. A full
demo run is about 26 operations.

Verification and export being free is why `verify` runs automatically after
every change rather than on request — there is no reason not to.

**One caveat on the timing numbers.** `elapsed_seconds` and
`in_request_seconds` are reported separately because they differ by more than
tenfold: an async edit spends about a second in the POST and twelve being
polled. An earlier version of this ledger summed request latencies and called
the result wall time, which understated a real run by an order of magnitude.

## Repository map

```
packet/
  order.py       the record, the field registry, and the audience rule
  templates.py   the six documents, and the renderer that knows what each carries
  diagram.py     the as-designed diagram, generated from the order
  superdocs.py   the API client — the four calls, the traps, the budget
  build.py       render → upload → manifest
  propagate.py   change → which documents → targeted edits → human gate
  verify.py      the three proofs
orders/          one synthetic order record
samples/         committed renders, and the internal-vs-customer diff
tests/           49 tests, none of which need a key
```

## What went wrong

Five defects, all found by pointing this at the real service. The offline suite
was green for a day before any of them appeared, which is the argument for this
section existing at all.

**The pack was never a pack.** Six documents uploaded to one session over
`upload-base64` produced *one* document — that endpoint replaces the session's
focused document rather than adding to it, and every call returns `200` while
doing so. The fix is the multipart endpoint with `open_mode=new_focused`, plus
reading the ids back from the session roster and treating that as authoritative.
The manifest now fails loudly if a document has no id, because the failure it
produced looked exactly like success.

**Verification was reading the wrong document.** `POST /v1/documents/export`
takes a `session_id` and no `document_id`, so in a multi-document session it
returns whichever document is focused. Every document in the pack was being
checked against the handover certificate. Six of twelve checks passed, by
coincidence, and the report looked healthy. It now reads each document's own
body from the roster.

**My instruction contradicted itself.** On an unprotected circuit, route
diversity and protection scheme both read "None — single path". The generated
instruction told the model to replace that one string with two different values,
and it resolved the contradiction differently in different documents — leaving
the internal and customer packs disagreeing about a contract term. Where two
changed fields share a before-value, the instruction now names the labelled row
instead of quoting the ambiguous string.

**A four-field turn applies some fields and skips others.** Measured repeatedly
on the live service; a single-field turn is reliable. Rather than make every
edit more expensive, there is one bounded repair pass: read back what landed,
re-send only what did not, one field per turn. It costs nothing when nothing was
skipped, and it will **never** re-send a change a reviewer rejected — a
rejection is a person saying no, and the repair pass cannot tell that apart from
a model skipping a field, so it defers.

**`--live` did nothing.** It passed `None`, which the verifiers read as "use
your default" — and their default is the local render. The flag reported a stale
pack as correct for an afternoon. A flag that quietly does nothing is worse than
no flag.

And one honesty fix: `wall_seconds` summed request latencies and excluded
polling, so a run whose edits each took ~13 seconds reported them as 0.8. It now
reports `elapsed_seconds` and `in_request_seconds` separately.

## Honest limitations

- **The customer pack removes internal sections rather than redacting them.** A
  page of `[withheld]` tells a customer exactly how much you are not telling
  them. Individual internal fields outside a block still redact, as a failsafe.
- **Change propagation is one operation per affected document.** A twelve-document
  change costs twelve operations. Batching them into one multi-document chat turn
  would be cheaper and is the obvious next optimisation, but it makes the human
  review coarser — you would approve a batch rather than a document — and for
  contract documents I would rather pay than blur the gate.
- **The reviewer is a terminal prompt.** It is a real gate with real per-change
  decisions, but a delivery manager wants this in a web UI or Slack. The
  `Reviewer` type is one function; wiring it to Slack's interactive messages is
  the shape it should take.
- **`verify --live` re-exports the whole session to read one document.** Free,
  but slow on a twelve-document pack. Per-document text retrieval would be
  better; the structure read already covers the "nothing else moved" half.
- **No e-signature.** The handover certificate has blank signature blocks by
  design. SuperDocs does not sign, and I am not going to pretend otherwise.
- **Wholesale diagram replacement is unreliable, and one document proves it.**
  Across three live runs and three different instruction phrasings — "replace
  the diagram", the same with a full replacement block inline, and an atomic
  section rewrite (the primitive the agent playbook says is atomic) — the
  *customer* scope of work regenerated its diagram correctly every time and the
  *internal* one did not. It edits the labels inside the existing diagram and
  leaves the topology single-path, so the document describes dual path in its
  table and draws a single path.

  What matters is that the build **says so**: `verify` compares the diagram's
  own declaration against the order, `packet change` runs that check
  automatically, and the run exits non-zero naming the document. A half-updated
  diagram is the worst kind of output, so it is reported rather than shipped.
  The honest position is that this works on one document and not the other, and
  I would rather say that than average it into "works".

  Workaround today: re-run `packet build --only 03-installation-scope-of-work`,
  which regenerates that document from the order record for one operation.

- **Send the pack as PDF, not Word, while it contains a diagram.** Verified
  against production: PDF renders the Mermaid diagram correctly; `.docx` drops
  it and leaves the raw source in the document as text, with no export warning.
  `packet export --format docx` raises its own warning naming the affected
  document. This is a service-side gap, reported, and not something this build
  can fix — but shipping a customer a contract pack with the network design
  replaced by unreadable source would be worse than saying so.
- **One order shape.** The registry is generic but only telecom access circuits
  are modelled. A second order type would test whether it is really generic; it
  has not been.
- **Rejected changes leave the document unedited but the order record updated**
  unless you skip `--write-back`. The next `verify` catches the divergence and
  says so, but reconciling it is manual.
- **The repair pass is one round, by design.** If a field will not land twice,
  that is a finding for a person rather than a loop to spin in — but it does
  mean a stubborn field ends as a reported failure, not a fixed document.
- **Measured latency:** ~2 s per document upload, ~13 s per `chat_async` edit at
  `model_tier: pro`. A twelve-document build is around 30 s; a twelve-document
  change is a few minutes. That is fine for a delivery manager and too slow for
  a UI that blocks on it.

## Notes

Everything in `orders/` is synthetic. Acme Manufacturing Holdings and Northstar
Connectivity Group do not exist; the addresses, contacts and circuit references
are invented. No real customer, supplier or contract is described.

No key is committed. `.env` is gitignored and `.env.example` carries a
placeholder.

Built by **Parth Saini** for the SuperDocs Round 2 engineer task. MIT licensed,
as per this repository.
