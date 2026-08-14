# Runbook Reconciler — build plan

This document is the brief for a fresh session. It is self-contained: read it end to
end and you can build the whole thing without the conversation that produced it.

**Working directory:** `extensions/CulturalProfessor/runbook-reconciler/` in the public
repo `github.com/superdocsapp/superdocs-builds`. Build inside this folder only; never
modify anything outside it (`CONTRIBUTING.md` requires this).

---

## 1. What this is and why it exists

SuperDocs is an API that makes **targeted edits inside existing documents** — upload a
document, send an instruction, review the proposed changes, approve them individually,
export the result. Their thesis: generating documents is solved, editing them is not.

This build is a **Task 2.2 kind-three invention** — not from the assigned card, not from
the 1,014-card open list. The novelty claim has been verified against that list: every
runbook, incident, DR and resilience card on it (`Method-of-procedure (MOP) doc builder`,
`Business continuity and disaster recovery plan builder`, `Blameless incident postmortem
builder`, `Incident agent: live incident document to postmortem`, `MCP pipeline: spec →
diagram-rich runbook`, `Operational resilience documentation pack`) is a **generator**.
None verifies an existing operational document against the infrastructure it describes.
The market is the same: FireHydrant, Rootly, PagerDuty and incident.io all automate
runbook *execution*; nobody checks whether the runbook is *true*.

**The product in one line:** infrastructure config is ground truth; runbooks in Confluence
are checked against it; findings go to a human; approved fixes land as surgical edits to
the exact passage with everything else on the page provably untouched.

**Hard boundary: we read DevOps files and write documents. We never edit infrastructure.**
A finding about a wrong Terraform value produces a ticket suggestion, never a write.

### Why runbooks and not a general wiki

An earlier version of this idea watched code and updated a general wiki. It was rejected
for a reason worth carrying: the verifiable surface of a general wiki is ~10%, so the tool
is either too narrow to install or too noisy to keep. A runbook is *mostly* commands,
resource names, thresholds, links and escalation targets — the verifiable surface is ~70%.
Same architecture, different document, and the coverage objection disappears.

### The two halves, and why the second is not optional

1. **The reconciler** — continuous, deterministic-first, cheap. Keeps runbooks true.
2. **The readiness pack** — periodic, formatted. Turns the same verified claim register
   into an on-call readiness report and an auditor-facing DR evidence document.

Be honest about this in the write-up: at a single document, an AI edit that fixes
`80%` → `90%` saves twenty seconds, and SuperDocs is barely earning its place. It earns it
at estate scale, in multi-document consistency (the same threshold in the runbook, the SLO
doc and the DR plan, kept in lockstep), and in half two. **Without half two this is a
linter with a nice UI.** That sentence belongs in the write-up.

---

## 2. Non-goals and rails

From the task document, and non-negotiable:

- **Not a document management system.** We edit and produce documents; we are not the archive.
- **No spreadsheet output.** Reading one as a source is fine.
- **No claimed certifications.** SOC 2 / ISO are the buyer's *motivation*, never our claim.
  If compliance comes up, the honest sentence is that certification is a roadmap
  conversation, not a current fact.
- **No live web browsing by SuperDocs.** Our own system fetches whatever it likes; the rail
  is about what their product does.
- **Never edit infrastructure files.**
- **No key in a repository, a log, a commit, a shell history, or a screenshot.** This folder
  goes into a public PR. If a token appears in the demo video, cover it with a solid box,
  never a blur.
- **Fabricated data only.** Fictional services and synthetic infra are expected. No real
  third-party data, no employer material.

---

## 3. Architecture

```
                    ┌─────────────────────────────────────────┐
 ground truth  ───► │  readers/    (pure, deterministic)      │
 (git, read-only)   │  alerts · k8s · ci · terraform · catalog│
                    └────────────────┬────────────────────────┘
                                     ▼
 Confluence  ─────► ┌─────────────────────────────────────────┐
 (storage format)   │  extract/    claims + byte anchors      │
                    └────────────────┬────────────────────────┘
                                     ▼
                    ┌─────────────────────────────────────────┐
                    │  CLAIM REGISTER  (SQLite, the spine)    │
                    │  agrees | contradicts | unverifiable    │
                    └──────┬───────────────────────┬──────────┘
                           ▼                       ▼
              ┌────────────────────┐   ┌──────────────────────┐
              │ reconciler         │   │ readiness pack       │
              │ passage → SuperDocs│   │ multi-doc + templates│
              │ → review → splice  │   │ → export             │
              └─────────┬──────────┘   └──────────────────────┘
                        ▼
              Confluence PUT (version-checked, one spliced range)
```

Both halves read the same register. Design the register first; neither half is a bolt-on.

### Layout

```
runbook-reconciler/
  reconciler/
    __init__.py
    superdocs.py        # COPIED from product-manual-builder (see §4)
    config.py           # dotenv, env resolution, declared mappings
    register.py         # claim register: schema, storage, queries
    claims.py           # claim types + anchors
    extract/
      storage.py        # Confluence storage-format parse → claims + byte offsets
    readers/
      alerts.py         # Prometheus / alerting rules
      kubernetes.py     # manifests, Helm values
      ci.py             # GitHub Actions / GitLab CI
      terraform.py      # HCL resources
      catalog.py        # Backstage catalog-info.yaml
    check/
      vertical.py       # claim vs ground truth
      coverage.py       # alert ↔ runbook bidirectional integrity
    confluence/
      client.py         # auth discovery, crawl, read
      splice.py         # locate → splice → assert → version-checked PUT
    edit.py             # passage → SuperDocs → approved text
    pack.py             # half two: readiness + DR documents
    review.py           # the human gate
    watch.py            # demo-mode watcher
    mcp_server.py       # machine interface
    cli.py
  fixtures/
    infra/              # synthetic ground truth
    runbooks/           # synthetic Confluence pages (storage format)
    expected.yaml       # planted drift + expected findings — the measurement key
  tests/
  docs/
  rr                    # bash entry point (bootstraps venv)
  selftest              # staged proof script
  preflight.py          # already written — setup diagnostic
  pyproject.toml
  README.md
  BUGS.md
  PROGRESS.md
  .env.example          # already written
  .gitignore            # already written
```

---

## 4. Borrow from `use-cases/CulturalProfessor/product-manual-builder`

Same author, same repo, MIT. **Copy, don't rewrite** — and note the provenance in each
copied file's docstring so it doesn't read as invented twice.

| Take | From | Why it matters |
|---|---|---|
| **`manualbuilder/superdocs.py`** → `reconciler/superdocs.py` | whole file | Live-verified client. Already solves: the JSON **double-parse** of `proposed_change_batch` (the single most common integrator bug), the approval trap where `approved` must appear at top level *and* per change, `QuotaExceeded` on 429, job polling that treats minutes-long runs as normal, continue-prompt handling, export returning bytes-or-JSON-or-URL, and `load_dotenv` that strips quotes. |
| `tests/stub_superdocs.py` | whole file | In-process HTTP stub. Lets tests run the real CLI as a subprocess, kill it mid-request, and prove crash recovery — no key, no spend. |
| `mb` → `rr` | pattern | Bootstraps `.venv` on first use, so a stranger's first command works before install. Also routes `rr test` and `rr fix`. |
| `selftest` | pattern | Staged proof script, cheapest first, offline stages need no key, live stages skip loudly rather than silently passing. Opt-in stage for anything that spends. |
| `pyproject.toml` | ruff + black config verbatim | See §5. |
| `BUGS.md` | format | What I did / expected / got / how badly it blocked / how to reproduce. |
| `tests/conftest.py` | pattern | Session-scoped fixture loading the corpus once. |

**Two facts already paid for, carry them forward:**

- **A session takes one turn at a time.** A second turn while one is outstanding returns
  `409 session_busy`. One turn edits **one** document — `document_ids` as a list is
  silently accepted and every change lands in the focused document. Multi-document
  consistency is bought at the **approval gate**, not in the request.
- **Documents have two ids.** The session-scoped `doc_…` is what a chat turn names; the
  UUID underneath is durable and is what reopens it elsewhere.

---

## 5. Conventions

### Linting and formatting — identical to the sibling build

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
extend-exclude = ["out", "*.egg-info"]

[tool.ruff.lint]
# Formatting is Black's job, run separately -- ruff here is lint-only, so E501
# is off; Black owns line length.
select = ["E", "F", "W", "I", "UP", "B", "SIM", "C4", "RUF", "A"]
ignore = ["RUF001", "RUF002", "RUF003", "E501"]

[tool.ruff.lint.isort]
known-first-party = ["reconciler"]

[tool.black]
line-length = 100
target-version = ["py311"]
```

`ruff check .` and `black --check .` run in `selftest` as **check-only** — a proof script
that rewrites what it is proving proves nothing. `rr fix` applies.

Dev deps: `pytest>=8.2`, `ruff>=0.16`, `black>=24`. Runtime: `httpx>=0.27`, `pyyaml>=6.0`.
Python `>=3.11`. `from __future__ import annotations` at the top of every module.

### Comments — why, not what

The bar: a comment earns its place only if it records something the code cannot say —
a decision, a trap, a thing that cost time to learn. Never narrate.

```python
# BAD — narrates
# Loop over the changes and approve each one
for change in changes: ...

# GOOD — records a trap that cost real time
# `approved` is sent at the top level as well as per change: it is the default
# for any entry that omits its own, and leaving it out approves nothing while
# looking exactly like a service that ignored the call.
```

Module docstrings carry the design decision and the dead ends. Where the live service
behaved differently from its documentation, say so **in the file that depends on it**, not
only in BUGS.md.

### Commits

Small and incremental — one per meaningful step, not one per stage. Message shape:
`area: what changed`, imperative, lowercase, body only where the *why* isn't obvious.
Commit only when `rr test` passes. Never commit `.env`.

### PROGRESS.md

Append an entry whenever an ambiguity is resolved by judgment rather than fact: the
question, the call, the reasoning. The task document says a logged assumption counts in
your favour.

---

## 6. The claim register — the spine

Design this first. SQLite, one file, `register.db`.

```python
@dataclass(frozen=True)
class Claim:
    claim_id: str          # stable hash of (page_id, anchor_hash, kind, subject)
    page_id: str           # Confluence page
    kind: str              # threshold | command | resource | link | escalation | version
    subject: str           # canonical entity, e.g. "deploy/api@payments"
    asserted: str          # what the runbook says
    anchor: Anchor         # how to find it again (see §7)
    excerpt: str           # the sentence, for the reviewer

@dataclass(frozen=True)
class Finding:
    claim_id: str
    verdict: str           # agrees | contradicts | unverifiable
    observed: str | None   # what ground truth says
    evidence: str          # file path + line — must resolve
    confidence: float
    proposed: str | None   # the replacement text, once SuperDocs has produced one
    decision: str | None   # approved | rejected | None
    applied_at: str | None
```

Rules:

- **`unverifiable` is a first-class verdict, never folded into `agrees`.** Report the count
  in every summary. A claim it could not check is reported as unchecked.
- **Every finding carries evidence that resolves** to a real file and line. A finding whose
  evidence doesn't resolve is a bug, and there is a test for it.
- **Idempotent by `claim_id`.** Re-running produces the same ids; an already-applied
  finding is never re-proposed.
- The register is the only thing both halves read.

---

## 7. Confluence — the part that decides whether this works

### Auth (already solved — do not rediscover this)

A **scoped** API token is rejected by the site host with `401`, which is indistinguishable
from a revoked credential. It only works through the gateway:

| Host | Basic | Bearer |
|---|---|---|
| `https://<site>.atlassian.net` | 401 | 403 |
| `https://api.atlassian.com/ex/confluence/{cloudId}` | **200** | **200** |

Resolve `cloudId` from `GET {site}/_edge/tenant_info` (no auth), then probe the three
combinations and use whichever answers 200 — so a classic token still works. `preflight.py`
already implements exactly this; lift `discover()` into `reconciler/confluence/client.py`.

Scopes on the token: `read:page`, `write:page`, `read:space`, `read:hierarchical-content`,
`read:content`, `read:label`, `write:label`, `read:comment`, `write:comment`, `read:user`
(all `:confluence`). `read:user` is load-bearing — it gives our own accountId, which is how
we ignore our own writes and avoid a self-trigger loop.

Verified working: page `98311` reads with `?body-format=storage`, 5,653 bytes, classic
XHTML with `<table data-layout="default">`. Pages created through the live-doc editor **are**
returned by the pages API — an earlier worry that they wouldn't be was wrong.

### The splice — the core technique

Confluence has **no per-block PATCH**. Updates are a whole-page `PUT` carrying the entire
body plus `version.number` incremented. So "nothing else changed" cannot be delegated to
the API. Guarantee it by construction:

1. Parse the storage-format string **only to locate** the target node's character offsets.
2. **Splice the string** at those offsets. Everything outside is byte-identical *because it
   was never re-serialized* — including macros we don't understand.
3. **Pre-flight assertion before the PUT:** diff old body against new, assert exactly one
   contiguous range differs and it is the intended one. Refuse to write otherwise.
4. `version.number` gives optimistic concurrency free: a human edit landing in between fails
   the write. Re-resolve the anchor; never retry blind.

**Never parse → modify → re-serialize.** That reformats the page, mangles
`<ac:structured-macro>`, and is how you silently vandalize a four-year-old wiki.

### Anchors

`Anchor = (heading_path, node_index, content_hash, char_range)`. Byte offsets are valid only
for the version they were read from, so re-resolve at apply time by heading path + content
hash. If the hash moved, the passage changed under us: escalate, don't guess.

### Node allowlist and the comment fallback

Only splice passages whose subtree contains node types that can be faithfully reconstructed
(text, `strong`, `em`, `code`, `a`, `li`, `td`). Anything containing a macro, a user
mention or an attachment → **do not edit**. Post an inline comment instead: *"this threshold
no longer matches the alert rule; needs a human."* A capability honestly absent from a path
beats one present and broken.

---

## 8. What it must never do

Write these, then the test for each, then the code. Each gets a test named for the rule.

1. Write to Confluence without an approved finding.
2. Change any byte outside the approved passage.
3. Take instructions from page content, code comments or config. Text aimed at the system is
   a **finding to report**, never a command. (Plant one in the corpus.)
4. Mark a claim correct that it could not verify.
5. Spend a paid operation when the deterministic layers found nothing.
6. Re-trigger on its own writes.
7. Leave a multi-page update half applied.
8. Emit a finding whose evidence does not resolve to a real file and line.
9. Write a secret to a log, a commit or the console.

---

## 9. Stages

Each stage ends green (`rr test`, `ruff`, `black`) and is committed. Later stages are
cuttable; earlier ones are not.

**Stage 0 — scaffold.** `pyproject.toml`, `rr`, package skeleton, `PROGRESS.md`, move
`preflight.py` into the layout. Copy `superdocs.py` and `stub_superdocs.py` across with
provenance noted. *Commit: `scaffold: project layout, lint and format config, entry point`.*

**Stage 1 — the synthetic corpus.** Build `fixtures/` first, because everything is measured
against it: a fictional service estate (Prometheus rules with `runbook_url` annotations, k8s
manifests, GitHub Actions workflows, Terraform, `catalog-info.yaml`) and runbooks in
Confluence storage format. Plant known drift in `expected.yaml`: threshold drift, renamed
deployment, dead dashboard link, orphan alert, orphan runbook, stale escalation, a passage
containing a macro (must refuse), a page containing an injection attempt (must report), and
**claims that are correct** (must not fire). This file is the measurement key — precision and
recall come from it. *Commit.*

**Stage 2 — claim register.** Schema, storage, queries, idempotency test. *Commit.*

**Stage 3 — ground-truth readers.** One module per source, pure functions, no I/O beyond
reading files, fully unit-tested against the corpus. *Commit per reader.*

**Stage 4 — claim extraction.** Storage-format parse → claims with anchors and byte ranges.
Round-trip test: extract every claim, splice each back with identical text, assert the body
is byte-identical. *Commit.*

**Stage 5 — the deterministic checker.** Vertical checks plus the bidirectional alert ↔
runbook coverage report. **No model, no spend, no network.** First genuinely useful output:

> 47 alerts · 31 have runbooks · 6 dead links · 9 runbooks referencing resources that no
> longer exist · 12 alerts with no runbook

Report precision/recall against `expected.yaml` including the cried-wolf rate. *Commit.*

**Stage 6 — Confluence adapter.** Auth discovery, crawl by label, read, splice, assertion,
version-checked PUT, comment fallback. Tests against recorded fixtures; one opt-in live test.
*Commit per piece.*

**Stage 7 — the SuperDocs edit path.** Passage + finding → `upload` → `chat` → proposed
changes → `approve` → `export` → mapped back to the anchor. **Batch every finding for one
page into a single request** — one operation covers up to 25 sections, so cost is 1 operation
per page per sweep, not per finding. *Commit.*

**Stage 8 — the review gate.** Terminal queue first: approve/reject item by item, rejecting
one leaves the rest, multi-page approvals apply as one transaction with rollback. *Commit.*

**Stage 9 — triggers.** `rr sweep` (the real one), `rr watch` (10s demo cadence, debounced,
coalesced, with a per-run cost line), CI action, and a **non-blocking** pre-commit nudge that
runs only the free local layer and always exits zero. A blocking hook that adds 30s to every
commit gets uninstalled. *Commit per trigger.*

**Stage 10 — the readiness pack (half two).** From the same register: on-call readiness report
and a DR evidence document. Templates, multi-document consistency, export. *Commit.*

**Stage 11 — MCP server.** `analyze`, `propose`, `approve`, `apply` as tools, so a machine can
drive the whole flow including the gate. *Commit.*

**Stage 12 — proof and packaging.** Measurement run with raw data committed, `README.md`,
`BUGS.md`, `selftest` complete, demo recording. *Commit.*

**Cut in this order if time runs short:** MCP → web UI (keep the terminal queue) → CI action.
**Never cut:** the deterministic checker, the splice assertion, the review gate, the tests for
§8. A modest build done immaculately beats an ambitious one left half-finished — they judge
within a band, not across.

---

## 10. Surfaces

| SuperDocs surface | Where | Stage |
|---|---|---|
| `upload` | passage as a small document | 7 |
| `chat` | the passage-scoped edit instruction, carrying the evidence | 7 |
| `approve` | per-finding decisions, top-level + per change | 7, 8 |
| `export` | the readiness pack and DR document; free, so lean on it | 10 |
| Multi-document | runbook + SLO doc + DR plan kept in lockstep | 10 |
| Templates | the readiness pack's house format | 10 |
| Review | the human gate | 8 |
| Search | **ours, not theirs** — SuperDocs search costs operations; do retrieval in local SQLite/embeddings | 5 |
| MCP | the machine interface | 11 |

| Ground-truth surface | Claims it settles |
|---|---|
| Prometheus / alerting rules | thresholds, severities, `runbook_url` |
| CI/CD workflows | job names, environments, approval gates |
| Kubernetes / Helm | deployment and namespace names, replicas, limits, probes |
| Terraform / Pulumi | resource names, regions, retention, backup schedules |
| Backstage `catalog-info.yaml` | ownership, tier, on-call team — also entity resolution |
| PagerDuty / Opsgenie config | escalation targets and schedules |

---

## 11. What gets measured

Method stated before result; variance reported; raw data committed under `docs/`; tail
behaviour, not just averages; limits admitted.

- **Precision, recall and cried-wolf rate** of the deterministic checker against
  `expected.yaml`, with the `unverifiable` bucket counted separately.
- **Cost per sweep.** Expect ~1 operation per page with findings. The headline number:
  *50 PRs/week × ~10% doc-relevant × ~2 pages ≈ 10 operations/week for a whole team.*
- **Zero-spend proof.** N sweeps with no drift must spend exactly 0 operations — asserted
  in a test, not claimed in prose.
- **Byte-identity.** Every applied edit asserts one contiguous changed range.
- **Resume.** Kill mid-sweep, restart, no duplicate writes and no lost findings.

---

## 12. Demo

Split screen: Confluence runbook, infra repo, findings panel.

1. Bump an alert threshold 80 → 90 and rename a k8s deployment. Commit.
2. Sweep: *3 findings across 2 runbooks — threshold drift, dead resource reference, dead link.*
3. Approve two, reject one. Confluence passages update; block-level diff proves the rest untouched.
4. Show the readiness report — coverage, orphan alerts, orphan runbooks.
5. **Change something irrelevant. Zero findings, zero operations.**
6. Ctrl-C mid-run, restart, it resumes without duplicating.

Beat 4 sells it; beats 5 and 6 prove it isn't a toy. Most submissions stop at 3.

**Recording notes:** send a warm-up request first — the first call in a fresh session is slow.
Deep operations take 30s to several minutes; edit honestly rather than faking speed. Claim only
what the recording shows.

---

## 13. Deliverables

- `README.md` — what it does, how to run, **what SuperDocs surfaces it uses**, a screenshot, a
  demo link, and the credit line "built for the SuperDocs task". Include the honest limitations
  section: scoped to git-declared config not live cloud state; two languages of symbol
  extraction; Confluence Cloud only, not Data Center; value decays after the first sweep.
- `BUGS.md` — every rough edge, in the sibling build's format. Bugs found earn points.
- `PROGRESS.md` — the assumption log.
- PR into `superdocsapp/superdocs-builds` with your name and one or two sentences. No email —
  public repo.
- Demo video, write-up and architecture diagram ride the submission form, not this repo.

---

## 14. Known risks

1. **Mature SRE teams keep runbooks as markdown in the repo** and need this least. The buyer is
   the large middle where runbooks live in Confluence. Say so rather than claiming universality.
2. **Entity resolution** — mapping "the payments service" in prose to `deploy/api` in namespace
   `payments`. Backstage catalog solves it where present; otherwise declared mapping in config.
3. **Placeholders.** Runbooks say `<your-namespace>` deliberately. Needs a convention, or the
   false-positive rate eats the product.
4. **Multi-repo.** Infra and service code live apart. Multi-repo from day one.
5. **Live docs and macros.** Both handled by the allowlist plus comment fallback.

Start at Stage 0. Write the must-never test before the code it constrains, every time.
