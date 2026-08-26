# GST Notice Reply Drafter

**Built ON SuperDocs** for the SuperDocs builder round, by **Nevil Sonani**.
An extra build beyond my assigned card — use case #3 from my market research:
mid-size CA firms drafting scrutiny-notice replies under deadline.

A GST ASMT-10 scrutiny notice arrives. The reply is 80% firm boilerplate and
20% case-specific facts — and a missed point can turn scrutiny into a
section 73 demand. This app drafts the complete, filing-ready reply and
**refuses to file an incomplete one**.

## What it does

1. **Saves the firm's standard reply template** to SuperDocs
   (`POST /v1/templates/upload` — the templates surface); the drafting chat
   finds it by search and uses it as the document structure.
2. **Attaches the notice** (`/v1/attachments/upload-base64`) so the AI reads
   the actual notice — reference numbers, DIN, periods, each numbered
   discrepancy.
3. **Drafts the reply** in one review-mode chat, constrained to the case
   facts (`case/case_facts.yaml`) supplied by the engagement team: figures
   may come ONLY from the facts or the notice; anything else must appear as
   "[information awaited from client]", never an invention.
4. **Human gate** — every proposed change is approved/rejected explicitly
   (`--auto-approve` for machine-driven runs).
5. **Exports** DOCX + Markdown, then runs a **completeness verifier**: every
   numbered discrepancy in the notice must have its reply section, the
   notice reference/DIN/GSTIN must be quoted exactly, every promised
   annexure must be cited, and no template placeholder may remain. Any miss
   **fails the run** — counted, not claimed.

## Quickstart

```bash
cd use-cases/nevilsonani/notice-reply-drafter
cp .env.example .env       # put your sk_ key in
uv run nrd run --auto-approve
uv run nrd verify-doc out/reply-XXXXXX.md
```

Cost: ~2 operations per full draft; exports free; `NRD_OP_BUDGET` is a hard
stop.

## The case (fictional, on purpose)

`case/` holds a synthetic FORM GST ASMT-10 (three discrepancies: GSTR-1 vs
3B outward mismatch, GSTR-2B ITC excess, section 50 interest) for a
fictional client, the fictional firm's reply template, and the engagement
team's case facts. All invented, as the task expects. The scenario is
realistic: credit notes netted in 3B, supplier-delayed invoices, voluntary
DRC-03 — the daily bread of scrutiny replies.

## What the verifier caught (a true story from this repo's first runs)

The very first live draft **fabricated everything the case didn't hand it**:
an invented reference number, an invented DIN, even an invented client
("ABC Enterprises") — plausible-looking and completely wrong. The
completeness verifier failed the run automatically. The fix was a
zero-fabrication instruction (identifiers enumerated, notice inline,
"no bracketed placeholder may remain"); the next run still lost two digits
of the DIN — caught again — and the third run passed with every identifier
exact. That is the build's thesis in one anecdote: **drafting is cheap;
refusing to file an unverified draft is the product.**

Also observed and reported: with template-driven drafting, the job sometimes
completes **without honoring `approval_mode: "ask_every_time"`** (no pending
changes to review — reproduced 2 of 3 runs). The app prints a loud warning
when that happens and the verifier still stands between the draft and the
filing.

## Honest limitations

- The verifier proves the reply is *complete and correctly referenced*, not
  that the legal position is *right* — that judgment stays with the CA at
  the gate, which is the point of the gate.
- One notice format (ASMT-10) parsed for discrepancy numbering in v1; other
  notice forms (DRC-01, ASMT-14) are a regex + template away — data changes,
  not rewrites.

*Built for the SuperDocs task. Same client core as my Site Survey build
(warmup retry, job polling, second-parse, budget stop) — proven once,
reused.*
