# Negotiation Playbook Pack

Built for SuperDocs Round 2, Task 2 (assigned build). By aadik1ng.

## What this is

Two things, per the brief: (1) `playbook.yaml` — a negotiation playbook for
GPU-compute/cloud SLA vendor contracts, 15 points, each with an opening
position, a concession sequence, a trade, a required approver, and the
words to use. (2) `generate_brief.py` — turns that playbook plus an inbound
contract into the artifact a deal desk actually wants: a one-page
negotiation brief, generated *on SuperDocs' own document-editing API*, not
a side pipeline that happens to produce similar-looking text.

## How it's built on SuperDocs

The minimum four-call contract from the brief — upload, edit instruction,
approve, export — done for real, live, against the production API:

1. **Upload** (`POST /v1/documents/upload-base64`) the inbound contract into
   a fresh session.
2. **One** targeted chat instruction (`POST /v1/chat/async`,
   `approval_mode=ask_every_time`) that hands SuperDocs' own document agent
   all 15 playbook points (topic, our worst-acceptable floor, required
   approver) and asks it to append a "Negotiation Brief" section: a verdict
   per point (Compliant / Conflicting / **Silent** — explicitly never
   "Compliant" for a point the contract never touches), the approver for
   anything escalated, and the source clause it's based on. One call, not
   fifteen — the brief itself warns to budget operations.
3. **Poll + approve** (`GET /v1/jobs/{id}`, `POST /v1/chat/{session}/approve`)
   the proposed change through SuperDocs' own human-in-the-loop gate before
   it touches the document.
4. **Export** (`POST /v1/documents/export`, markdown/docx/pdf) the finished,
   one-page brief.

## Run it

```bash
pip install httpx pyyaml
export SUPERDOCS_API_KEY=sk_...   # see "getting a key" below
python generate_brief.py sample_inbound_contract.md
# -> writes sample_inbound_contract_negotiation_brief.md
```

**Getting a key:** `POST /v1/agents/signup` with `{"agree_to_terms": true}`
returns an `sk_...` key on the free tier (500 ops/month) — shown once, no
human login step required. See `docs.superdocs.app/introduction/agent-signup`.

## Proof it actually works

`sample_inbound_contract_negotiation_brief.md` in this folder is a **real
export from the live API**, produced exactly the way `generate_brief.py`
produces it (same upload → one chat instruction → approve → export flow,
run against `sample_inbound_contract.md`, a synthetic "HeliosGrid Compute"
GPU-SLA contract that touches 8 of the 15 playbook points and is silent on
the other 7). Check it against the playbook and the source contract:

- Points the contract never mentions (downtime definition, SLA remedy,
  claim deadline, indemnification, data export rights, maintenance notice,
  force majeure, audit rights) are correctly marked **Silent**, not
  Compliant — the brief's own "what strong looks like" bar.
- Uptime is correctly marked **Compliant**, quoting the actual clause.
- Approver routing matches the playbook (`Remedy for an SLA breach` →
  Finance, `Overall liability cap` / `IP indemnification` → General
  Counsel, `Data deletion` / `Guaranteed capacity` → the correct
  role-specific approvers per point).
- Rest of the document (all 8 original clauses) came back byte-identical
  below the inserted brief — nothing else was touched.

## Honest limitations (found by actually running this, not guessed)

**Two verdicts in the real output are wrong, and it's a real product-side
miss, not a fabrication.** `Termination without cause` and `Duration of
quoted pricing` are both marked **Conflicting**, with source notes
`"[Standard termination language absent/not found]"` and `"[Pricing terms
not specified]"` — but the sample contract's Section 5 ("Customer may
terminate this Agreement for convenience upon 60 days written notice...")
and Section 7 ("Quoted per-GPU-hour pricing is fixed for the initial
12-month term...") plainly cover both. The model didn't invent facts (it
didn't claim a clause exists that doesn't), it just failed to connect the
right existing clause to the right playbook point for these two — an
attention/retrieval miss on SuperDocs' side, reproducible, worth a bug
report through their in-app button. Reporting it here rather than hiding
it, per the brief's own "honesty over fabrication" standard.

**The verdict itself is the model's own judgment**, not a deterministic
comparison against `concession_sequence` the way a rules engine would do
it — this build leans on SuperDocs' document agent to do the actual
reasoning (that's the point of building *on* SuperDocs rather than beside
it), which trades determinism for staying genuinely inside the product's
surface. A stricter version could pass the full concession sequence and
ask for the specific rung the contract lands on rather than one binary
verdict; the single-instruction, one-operation version here was chosen to
stay cheap and fast, per the brief's own advice to budget operations.

**The brief landed at the top of the document, not literally "the end"**
as the instruction asked — a minor instruction-adherence miss, harmless
here (still one clearly-labeled section, still traceable), but worth
knowing if positioning matters for a given host document.

## Files

- `playbook.yaml` — the 15-point playbook.
- `generate_brief.py` — the standalone script (REST API, no MCP dependency).
- `sample_inbound_contract.md` — synthetic inbound contract used for the proof run.
- `sample_inbound_contract_negotiation_brief.md` — the real exported output.
