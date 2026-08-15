# Runbook Reconciler

Operational runbooks describe infrastructure that changes underneath them. The alert
threshold moves, the deployment gets renamed, the dashboard link rots, the escalation
team stops existing — and the runbook keeps saying what it said, until someone reads it
at 3am and it is wrong.

This tool reads infrastructure config as ground truth, checks whether the runbooks in
Confluence still tell the truth about it, and puts the differences in front of a human.
Approved fixes land as surgical edits to the exact passage, with every other byte on the
page provably untouched.

**It reads DevOps files and writes documents. It never edits infrastructure.** A finding
about a wrong Terraform value produces a ticket suggestion, never a write.

Everything in this README that is a number was produced by a command in this repository,
and the command is named next to it.

---

## Two minutes to the first output

No Confluence site, no API key, no network. The repository ships a synthetic estate and a
set of runbooks with drift planted in them.

```bash
cd extensions/CulturalProfessor/runbook-reconciler
./rr check --corpus
```

`./rr` builds its own virtualenv on first use, so this works on a fresh clone.

```
7 alerts · 4 have runbooks · 1 dead links · 1 runbooks referencing resources that no
longer exist · 2 alerts with no runbook

13 findings across 7 runbooks · 49 claims verified · 8 could not be checked · 0 paid operations

  [page 1001] alert:PaymentsApiHighLatency:threshold
      says the threshold in the alerting rule that actually pages someone
      observed: 1.2
      evidence: fixtures/infra/platform-infra/monitoring/payments.rules.yml:6
  ...
```

Every finding names the file and the line that proves it. There is a test asserting that
a finding whose evidence does not resolve is a failure.

---

## What it measures about itself

`fixtures/expected.yaml` — the measurement key — was written at stage 1, **before the
checker existed**, so precision and recall are scored against planted drift rather than
against whatever the implementation happened to find.

```bash
./rr measure
```

| | |
| --- | --- |
| Precision | **1.000** |
| Recall | **1.000** |
| Cried-wolf rate | **0.000** |
| Claims verified | 49 |
| Claims it could not check | 8 — counted separately, never folded into "verified" |
| Paid operations for all of the above | **0** |

Raw data: [`docs/measurement.json`](docs/measurement.json). Test suite: 267 passing.

*Demo recording: not yet linked. It rides the submission form rather than this repository,
and there is no screenshot here rather than a staged one — every output in this README is
copied from a real run you can reproduce with the command above it.*

**What this number is and is not.** It is a real score against a key written in advance,
on a corpus of 8 runbooks and ~40 config files. It is not evidence of how the checker
behaves on somebody's real 400-page space, where the interesting failure is false
positives from prose the extractor was never designed for. The honest claim is that the
method is sound and measured; the sample is small and synthetic, and was built by the
same person who wrote the checker.

---

## The full loop

```bash
./rr check                 # free: no model, no network unless Confluence is configured
./rr propose               # prices the work in operations — spends nothing
./rr propose --yes         # the only command in this project that can be charged for
./rr review                # decide finding by finding; writes only what you approved
./rr pack                  # the readiness report and the DR evidence document (free)
./rr watch                 # sweep when the estate changes, debounced and coalesced
./rr status                # what the register holds, and what is parked
./rr mcp                   # the four tools, over stdio, for an agent
```

`./rr test` runs the suite; `./selftest` runs the staged proof, cheapest first, with the
stages that spend opt-in and loudly skipped rather than silently passed.

### The claim register is the spine

Both halves read one SQLite file. The reconciler writes claims and findings into it; the
readiness pack formats the same rows. There is no second store, so a coverage number that
disagrees with the review queue is impossible by construction rather than by discipline.

Every finding is one of three things, and the third is not hidden: **agrees**,
**contradicts**, or **unverifiable**. A claim it could not check is reported as
unchecked, never as correct.

### Half two: the readiness pack

```bash
./rr pack --out out/
```

Produces an **on-call readiness report** (per service: runbook, verified, drift,
unchecked, status) and a **DR evidence document** (what the estate declares about backup
and recovery, what the documentation says, and — with equal weight — what could not be
checked). Both carry their own limitations inside the document, because they get printed
and forwarded and read a year later by somebody who never saw this repository.

Neither document ever claims a certification. SOC 2 and ISO are the buyer's motivation
for wanting this; they are not something this tool asserts, and there is a test enforcing
that.

This half is why the project is not a linter. At a single document, an AI edit that fixes
`80%` to `90%` saves twenty seconds. It earns its place at estate scale, in
multi-document consistency, and here.

---

## What it checks

| Ground truth | Claims it settles |
| --- | --- |
| Prometheus / alerting rules | thresholds, severities, `runbook_url` links |
| CI/CD workflows | job names, environments, approval gates |
| Kubernetes / Helm | deployment and namespace names, replicas, limits, probes |
| Terraform | resource names, regions, retention, backup schedules |
| Backstage `catalog-info.yaml` | service ownership, tier, on-call team, entity resolution |
| PagerDuty / Opsgenie config | escalation targets and schedules |

Adding a rule is a YAML entry in [`config/checks.yaml`](config/checks.yaml), not a Python
function. Entity resolution comes from the Backstage catalog where one exists and from
[`config/mappings.yaml`](config/mappings.yaml) where it does not.

---

## How the surgical edit works

Confluence has **no per-block PATCH** — every update is a whole-page `PUT` carrying the
entire body and an incremented version number (see [BUGS.md](BUGS.md) item 5). So
"nothing else changed" cannot be delegated to the API. It is guaranteed by construction:

1. Parse the storage-format body **only to locate** the target node's character range.
2. Splice the original string at those offsets. Everything outside is byte-identical
   *because it was never re-serialized* — including macros the tool does not understand.
3. Before the `PUT`, diff old body against new and assert exactly one contiguous range
   differs and that it is the intended one. Refuse to write otherwise.
4. The version number gives optimistic concurrency free: a human edit landing in between
   fails the write rather than overwriting it.

Never parse → modify → re-serialize. That reformats the page, mangles
`<ac:structured-macro>`, and is how you silently vandalise a four-year-old wiki.

Passages containing node types that cannot be faithfully reconstructed — a macro, a user
mention, an attachment — are **never spliced**. They get an inline comment asking for a
human instead. A capability honestly absent beats one present and broken.

---

## What it must never do

Each of these has a test named for it in [`tests/test_must_never.py`](tests/test_must_never.py).

1. Write to Confluence without an approved finding.
2. Change any byte outside the approved passage.
3. Take instructions from page content, code comments or config. Text aimed at the system
   is a finding to report, never a command. (There is one planted in the corpus.)
4. Mark a claim correct that it could not verify.
5. Spend a paid operation when the deterministic layers found nothing.
6. Re-trigger on its own writes.
7. Leave a multi-page update half applied.
8. Emit a finding whose evidence does not resolve to a real file and line.
9. Write a secret to a log, a commit or the console.

---

## What it costs

The deterministic layer is free and does all of the finding. SuperDocs is entered only to
*word* a correction a human is about to review, and every finding on a page is batched
into one request: **one paid operation per page per sweep, not one per finding.**

On the headline estimate — 50 PRs a week, roughly a tenth of them doc-relevant, about two
pages each — that is around **ten operations a week for a whole team**.

A sweep over an estate with no drift spends exactly zero, and that is asserted in a test
rather than claimed here. `rr propose` prints the exact price and does nothing until you
pass `--yes`.

---

## Setup for a real estate

```bash
cp .env.example .env      # then fill it in; .env is gitignored
python3 preflight.py      # diagnoses auth before anything else runs
```

| Variable | What it is |
| --- | --- |
| `CONFLUENCE_BASE_URL` | `https://your-site.atlassian.net` |
| `CONFLUENCE_EMAIL` | the account the API token belongs to |
| `CONFLUENCE_API_TOKEN` | scoped token — see the scope list in `.env.example` |
| `CONFLUENCE_SPACE_KEY` | optional; narrows the crawl |
| `INFRA_REPO_PATHS` | comma-separated local checkouts. Multi-repo from day one |
| `SUPERDOCS_API_KEY` | only needed for `propose` and `pack --export` |
| `RR_SOURCE` | `auto` (default), `corpus`, or `confluence` |

Read-only credentials are enough for everything except `review` and `apply`.

**Triggers**, as templates rather than installed files — this repository holds other
people's projects and a workflow at its root would run on all of them:

- [`ci/github-actions.yml`](ci/github-actions.yml) — copy to `.github/workflows/` in the
  repository holding your infra. Runs the free layer only and holds no write credentials.
- [`hooks/pre-commit`](hooks/pre-commit) — always exits zero, and prints nothing unless
  there is drift. A blocking hook gets uninstalled in week one.

---

## SuperDocs surfaces used

| Surface | Where | Why |
| --- | --- | --- |
| `upload` | `edit.py`, `pack.py` | the passages as a small document; the pack as HTML |
| `chat` | `edit.py` | the passage-scoped edit instruction, carrying the evidence |
| `approve` | `edit.py`, `review.py` | per-finding decisions, top level *and* per change |
| Review | `review.py` | the human gate, which everything passes through |
| `export` | `pack.py` | the readiness and DR documents, through the house template |
| Multi-document | `pack.py` | the same fact in several documents, kept in lockstep |
| MCP | `mcp_server.py` | `analyze`, `propose`, `approve`, `apply` for an agent |

Search is deliberately **ours, not theirs** — SuperDocs search costs operations, so
retrieval happens in local SQLite.

The instruction sent to SuperDocs is built entirely from the *finding* — subject, asserted
value, observed value, evidence path. Page prose travels as the document being edited and
never as part of the message. That is the structural half of rule 3: a page containing
"ignore all previous instructions" cannot reach a model as an instruction, because no code
path puts page text into one.

---

## Honest limitations

- **Git-declared config, not live cloud state.** A resource deleted by hand still looks
  declared. Dead dashboard links are resolved against declared dashboards; nothing is
  fetched, deliberately — a checker whose output depends on whose Grafana is up is not
  deterministic.
- **Confluence Cloud only.** Not Data Center. The auth discovery and the v2 API are Cloud
  specific.
- **Mature SRE teams keep runbooks as markdown in the repo** and need this least. The
  buyer is the large middle where runbooks live in Confluence.
- **Value decays after the first sweep.** The first run finds years of accumulated drift;
  the tenth finds last week's. That is the correct shape for the product and a bad shape
  for a demo, and it is worth saying which one you are looking at.
- **Placeholders are a convention, not magic.** `<your-namespace>` is treated as
  unverifiable. A team writing placeholders another way will see false positives until
  they say so in config.
- **Label filtering costs one extra call per page** because CQL search is unreachable with
  a scoped token ([BUGS.md](BUGS.md) item 2). On a very large space that dominates a sweep.
- **The two halves have been run live separately, not as one continuous sweep.** The
  SuperDocs edit path spent 11 real operations against the corpus on 2026-08-15, and the
  Confluence read/write round trip is verified against a real page. What has not been done
  is a single live sweep that reads a real Confluence space, proposes, and writes back to
  it.
- **`rr watch` has not run long enough against a live space to provoke the self-trigger
  case.** The version ledger that prevents it is unit-tested; the loop has not been
  observed in production.

---

## Layout

```
reconciler/
  register.py      the claim register — the spine both halves read
  claims.py        claim identity, derived from text and heading path, never position
  readers/         ground truth: alerts, k8s, ci, terraform, catalog, escalation, dashboards
  estate.py        entity resolution — exact matches only, no fuzzy fallback
  extract/         storage-format parse → claims with byte anchors
  check/           the deterministic layer, driven by config/checks.yaml
  confluence/      auth discovery, the live adapter, the corpus, the splice
  edit.py          findings → SuperDocs → proposed wording
  review.py        the human gate
  apply.py         two-phase write with compensating rollback
  pack.py          half two
  watch.py         the trigger
  mcp_server.py    the machine interface
fixtures/          synthetic estate, runbooks, and expected.yaml (the measurement key)
docs/              measurement raw data
```

Further reading, in the order it is worth reading: [PLAN.md](PLAN.md) (the design brief),
[BUGS.md](BUGS.md) (what the APIs actually did), [PROGRESS.md](PROGRESS.md) (every
judgement call and its reasoning).

---

## Credit

Built by Vinayak (GitHub: [CulturalProfessor](https://github.com/CulturalProfessor)) for
the SuperDocs task.

The SuperDocs client and the test stub are copied from
`use-cases/CulturalProfessor/product-manual-builder` in this repository — same author,
same MIT licence — with provenance noted at the top of each file.
