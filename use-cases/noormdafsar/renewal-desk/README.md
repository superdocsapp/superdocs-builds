# Renewal Desk

A renewal quote and price-change notice batch, built on the SuperDocs API.

For a list of accounts coming up for renewal, it produces two documents per
account — a renewal quote and a price-change notice — where the notice explains
the change in terms specific to *that* account's plan and usage. Anything above a
defined increase goes to a human before the batch can be called complete. The
batch reports which accounts it deliberately did not process, and why.

Every account, person, email and figure in `data/` is fabricated.

## Demo

[![Renewal Desk — SuperDocs Round 2 demo](https://img.youtube.com/vi/1mYrkar390M/hqdefault.jpg)](https://youtu.be/1mYrkar390M)

[Watch on YouTube](https://youtu.be/1mYrkar390M) · [copy on Google Drive](https://drive.google.com/file/d/1emNluMiY8ajLE6K-C1kzolFiDbzO8KZv/view?usp=sharing)


---

## What it does, concretely

Run against the ten fabricated accounts in `data/accounts.json`, one live batch
produced this (the full ledger is [`samples/batch-report.md`](samples/batch-report.md)):

| | |
|---|---|
| Accounts in the list | 10 |
| Deliberately not processed | 3, each with a named reason |
| Auto-approved and exported | 3 |
| Held for a human | 4 |
| Approved by the reviewer | 3 (one after a revision) |
| Rejected by the reviewer | 1 — nothing was produced for it |
| SuperDocs operations spent | **13** |

Two documents per processed account, exported as DOCX.

---

## The one decision everything else follows from

**Python computes every number. The AI only writes prose.**

`pricing.py` derives each renewal price from `data/pricing_policy.json` — the
annual adjustment, seat-overage bands, usage-tier crossings, growth thresholds,
promo expiry, volume bands, multi-year locks, and the 15% cap. The model is then
handed those figures as exact strings and told to use them verbatim.

Afterwards, `verify_fill()` checks the returned document actually contains every
required figure and that no `[PLACEHOLDER]` survived. A document that fails
verification gets one repair turn; if it still fails, it is **never exported**.

This is why the prices in these letters can be asserted rather than trusted:
`test_pricing.py` checks them with no API key and no network.

```
$ python test_pricing.py
account         old      new     pct  gate   drivers
------------------------------------------------------------------------------
ACM-1042     $42.00   $47.88  +14.0%  HUMAN  4 driver(s)
NWL-2087     $30.00   $30.90   +3.0%  auto   1 driver(s)
BPA-3310     $45.00   $49.95  +11.0%  HUMAN  3 driver(s)
CHS-0771               -- skipped --  open billing dispute; renewal paperwork
DRM-5518               -- skipped --  usage data is missing, so an account-spe
EVR-6205               -- skipped --  renewal date is outside the run window;
FMF-7742     $40.00   $36.00  -10.0%  auto   1 driver(s)
GSC-8830     $32.00   $32.96   +3.0%  HUMAN  1 driver(s)
HLB-9114     $35.00   $40.25  +15.0%  HUMAN  2 driver(s)
IWC-1201     $30.00   $30.00   +0.0%  auto   1 driver(s)

all pricing checks pass
```

A new pricing rule is an edit to `pricing_policy.json`, not a code change.

---

## Account-specific, not a merge-field swap

The card asks that each notice be *genuinely* account-specific. Here is the
actual generated explanation for ACM-1042, unedited
([full letter](samples/ACM-1042-price-change-notice.md)):

> Your current use is above the seat count in your contract. You have **311
> active seats against 250 contracted seats**, and your team uses **workflow
> automation every day and audit exports every week**. Your average monthly API
> calls have climbed from **910,000 to 1,840,000**, and they crossed the 1M-call
> tier in **March 2026** and stayed above it every month since. That usage
> pattern, along with **102% year-over-year growth**, is why this change applies
> to your account.

Every fact in that paragraph is drawn from that one account's record, and each
one maps to a driver the pricing engine actually fired. Compare it with
[FMF-7742](samples/FMF-7742-price-change-notice.md), whose price went *down*
because it qualified for a volume band, or
[IWC-1201](samples/IWC-1201-price-change-notice.md), whose price did not move at
all because of a multi-year lock.

---

## The approval gate holds

An account is gated when any of these is true (all configurable):

- the increase is above **8%**
- the price-driven annual delta is above **$5,000**
- the account carries a **`churn_risk`** flag and the price moves at all

Gated accounts go through `POST /v1/chat/async` with
`approval_mode: "ask_every_time"`, and park at `awaiting_approval`. Nothing is
applied and nothing is exported until a person runs `decide`.

**The gate caught real problems in the live run.** Three of the four gated
drafts had defects a human should stop:

| Account | What the draft did | Verdict |
|---|---|---|
| ACM-1042 | Clean — second person, correct facts | approve |
| BPA-3310 | Wrote "**Our** plan… do not change" when it meant the customer's | fixed at the prompt, then approve |
| HLB-9114 | **Fabricated**: *"your request for a headline change has been approved"* — no such request exists | revise → approve |
| GSC-8830 | **Leaked our internal churn flag** into the customer's letter: *"resolving any outstanding renewal sentiment concerns"* | **reject** |

The rejection is not cosmetic. `samples/GSC-8830-price-change-notice.md` is the
document as it stands after the rejection — **still full of unfilled
placeholders**, because nothing was ever applied. A rejected account produces no
customer-facing document at all, and the reason is recorded in the batch report.

`report` exits non-zero while any non-skipped account is still unresolved, so a
CI job or a scheduler cannot mistake a half-reviewed batch for a finished one.

---

## What it deliberately did not process

Three accounts were skipped, each for a stated reason rather than silently:

| Account | Why |
|---|---|
| CHS-0771 | Open billing dispute; renewal paperwork is held until it closes |
| DRM-5518 | Usage data is missing, so an account-specific notice cannot be honestly written |
| EVR-6205 | Renewal date is outside the 60-day run window; belongs to a later batch |

DRM-5518 matters most: the honest response to missing data is to produce
nothing, not to write a vague letter that pretends to be personalised.

---

## Running it

**No local Python?** `run.sh` (macOS/Linux/Git Bash) and `run.cmd` (Windows)
run the CLI inside `python:3.12-slim` with this folder mounted. Same arguments,
nothing to install beyond Docker:

```bash
./run.sh plan
./run.sh run --sample 1
```

With Python available, call it directly:

```bash
cp .env.example .env        # then put your key in it
# or: export SUPERDOCS_API_KEY=sk_...

python test_pricing.py          # deterministic checks, no key, no network
python renewal_desk.py plan     # what the batch would do — zero API calls

python renewal_desk.py run --sample 1      # one account first, day-one mode
python renewal_desk.py run                 # the whole batch

python renewal_desk.py review              # what is waiting on a human
python renewal_desk.py decide ACM-1042 approve
python renewal_desk.py decide HLB-9114 revise --feedback "the opening invents a request"
python renewal_desk.py decide GSC-8830 reject --feedback "at-risk account, CS calls first"

python renewal_desk.py report              # ledger; exit 1 while incomplete
```

Python 3.11+, **standard library only** — no pip install. `setup-templates`
registers the two HTML templates in the SuperDocs template library.

---

## SuperDocs surfaces used

| Surface | Where |
|---|---|
| **Chat** (`POST /v1/chat`) | Deterministic template fills for quotes and ungated notices |
| **Async chat** (`POST /v1/chat/async`) | Every gated notice — HITL requires the async workflow |
| **Review / HITL** (`/v1/chat/{session}/approve`) | The approval gate: per-change approve, deny-with-feedback, reject |
| **Jobs** (`GET /v1/jobs/{id}`) | Polling, including both flavours of `awaiting_approval` |
| **Export** (`POST /v1/documents/export`) | DOCX for delivery, Markdown for the samples in this folder |
| **Templates** (`POST /v1/templates/upload`) | Both document templates registered in the library |
| **Sessions** | One session per document per account, so every letter has its own revisable history |
| **Model tiers** | `pro` for customer-facing prose, default for mechanical fills |

---

## Notes for anyone integrating

Things that cost me time, written down so they do not cost you any:

- **The documented second parse is conditional.** `metadata.pending_changes`
  arrived as a real array on this deployment, not a JSON-encoded string.
  `parse_pending_changes()` in `superdocs_client.py` handles both shapes, which
  is the safe way to write it.
- **`approved` is required at the top level of every approve call**, including
  batch shapes where each entry carries its own `approved`. Omitting it is a
  generic `422`.
- **Denying with feedback does not always re-propose.** The docs say the AI
  "may" propose a revision. On this run it sometimes settled the job to
  `completed` instead. A revision that never paused is a revision nobody
  reviewed, so `revise` detects that and re-drafts as a fresh gated turn rather
  than accepting whatever landed.
- **Denied changes are not billed.** A rejected account cost 1 operation, not 2.
- **Exports are free.** Export early and often; it costs nothing.

---

## Where it falls short

- **The prompt is the only thing keeping tone right.** The pronoun error and the
  fabricated opening were fixed by tightening instructions and re-running. There
  is no deterministic check for "does this read like a letter" — only the human
  gate. That is honest, but it means an ungated account could ship prose nobody
  read. Raising the gate to catch *all* accounts would be a config change.
- **Verification checks figures and placeholders, not claims.** It confirms
  `$47.88` appears; it cannot confirm the sentence around it is true. The
  fabricated HLB opening passed verification and was caught by a person.
- **Only US-dollar, per-seat, monthly pricing.** Currency conversion, tiered or
  usage-based pricing, and tax treatment are all out of scope.
- **No delivery.** It produces the documents; sending them is somebody else's
  system.
- **State is per-account files.** An earlier version used a single shared
  `state.json` and two concurrent CLI invocations clobbered each other's
  accounts — one that had been exported came back as `failed`. Per-account files
  make that race structurally impossible, but there is still no locking *within*
  one account, so do not run two commands against the same account at once.

---

## Layout

```
renewal-desk/
├── renewal_desk.py        the CLI: plan, run, review, decide, finalize, report
├── pricing.py             deterministic pricing + gate + skip rules
├── superdocs_client.py    stdlib SuperDocs REST client (retries, 429s, usage ledger)
├── test_pricing.py        pricing checks — no key, no network
├── data/
│   ├── accounts.json      10 fabricated accounts
│   └── pricing_policy.json  every rule and threshold
├── templates/             the two HTML templates
└── samples/               real output from a live run, plus the batch report
```

Built for the SuperDocs Round 2 engineering task.
