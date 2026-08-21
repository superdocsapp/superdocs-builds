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

**Which card this is.** The open list's **Documentation drift detector** (S3, extensions
folder). Its mechanism is this one: report the document, the section, the sentence and the
evidence; separate what could not be verified from what is correct; propose targeted fixes
for review; measure precision and recall against a seeded drift corpus. Two things here are
not on that card, or on any other card in the list. The card's ground truth is another
document — a changelog, a spec snapshot, a style guide — where this reads a **running
system's declared state**: Prometheus rules, Terraform, Kubernetes, the Backstage catalog.
And half two runs the other way round, turning verification *output* into a document rather
than consuming one.

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

13 findings across 7 runbooks · 50 claims verified · 8 could not be checked · 0 paid operations

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
| Claims verified | 50 |
| Claims it could not check | 8 — counted separately, never folded into "verified" |
| Paid operations for all of the above | **0** |

### The other corpus: pages with nothing wrong with them

Precision on planted drift measures whether the checker finds what is there. It says
nothing about what it **invents** on prose that has nothing wrong with it, and that is the
number that decides whether a team leaves the tool switched on.

So `fixtures/negative/` holds runbooks that are **true** about the same estate, written in
the ways the extractor was not tuned for: correct values in other units (`1200ms` against
a rule storing `1.2` seconds), templated commands in four placeholder dialects, a DR table,
and CamelCase prose that is not an alert name. There is no key to write, because the
expected output is zero. The same `./rr measure` scores it.

| | |
| --- | --- |
| Correct pages | 4 |
| Claims made on them | 27 |
| False positives | **0** |
| Of those claims, settled against ground truth | 18 |
| Reported unverifiable | 9 |

The second-to-last row is why the zero means something: a checker that shrugged at
everything would also score zero false positives, so there is a test asserting that most
of these claims come back **confirmed** rather than unchecked.

Writing this corpus immediately paid for itself. It found a bug where one templated
command — `kubectl rollout restart deploy/SERVICE_HERE` — made `SERVICE_HERE` the claim
naming the page's subject service, and the page-level pass then condemned the entire page
as a runbook for a service that no longer exists. A page-level false positive does not cost
one finding; it costs the page.

Raw data: [`docs/measurement.json`](docs/measurement.json). Test suite: 286 passing.

*Demo recording: not yet linked. It rides the submission form rather than this repository,
and there is no screenshot here rather than a staged one — every output in this README is
copied from a real run you can reproduce with the command above it.*

**What these numbers are and are not.** They are real scores: one against a key written in
advance, one against a corpus whose expected output is zero by construction. Both are on 12
runbooks and ~40 config files. Neither is evidence of how the checker behaves on somebody's
real 400-page space. The negative corpus narrows that gap — it is the first evidence here
about the failure mode that actually matters — but it was written by the same person who
wrote the checker, and prose nobody has thought of is exactly what it cannot contain. The
honest claim is that the method is sound, measured in both directions, and small.

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

There are three scripts, and they are for three different things:

| | |
| --- | --- |
| `./rr test` | the suite — 286 tests, no key, no network |
| `./selftest` | unattended pass/fail proof, cheapest first, live stages opt-in |
| `./demo` | a **paced, narrated walkthrough**, one stage at a time, run for real |

### `./demo` — the whole thing, end to end, against a live space

Twelve stages, each printing what it costs before it runs, each waiting for Enter.
`./demo --offline` stops after stage 3 and needs no credentials at all.

It seeds a runbook with seven planted contradictions into your own Confluence space
(`seed.py`), sweeps it, prices the wording, buys it, puts every finding through the
human gate, shows the byte-level diff, sweeps again to show the drift gone, shows that
a clean estate spends nothing — then tries to delete the page, and tells you to do it
by hand when the token cannot (a scoped token has no delete scope).

A real run on 2026-08-16: all seven found, **five worded and two escalated**, and the
edits confined to a handful of ranges in a 2,708-byte body — everything else identical.

The two escalations are the honest part, and they are two different honest answers. The
dead dashboard link has no correct replacement at all, so no wording will ever be
produced for it. The stale rota is a case where the service kept returning the whole list
of valid rotas — `Fulfilment, Payments Core, Tracking` — and the guard refused it, because
one value becoming a list is not a correction. Both go to a human rather than into the
page.

That guard exists because an earlier run of this same walkthrough got past a weaker one
and wrote `latency stays above 1.2 for 10 minutes` into the page, having dropped the unit
the estate does not store. See [BUGS.md](BUGS.md) and `edit._sane`.

Stage 11 then reports *nothing to propose* — zero operations on an estate with nothing
left wrong.

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
- **An editor tab open on a page will silently revert what this tool writes.** The
  Confluence web editor keeps its own copy from when it was opened, ignores writes that
  arrive through the API, and autosaves over them. Version numbers do not help: the
  autosave is a valid new version, and nothing in the API exposes "a human has this open",
  so the tool cannot detect or refuse it. Every change it makes is one labelled version,
  revertible in two clicks — that, plus sweeping when people are not editing, is the whole
  mitigation. Found the hard way; [BUGS.md](BUGS.md) item 14.
- **Mature SRE teams keep runbooks as markdown in the repo** and need this least. The
  buyer is the large middle where runbooks live in Confluence.
- **Value decays after the first sweep.** The first run finds years of accumulated drift;
  the tenth finds last week's. That is the correct shape for the product and a bad shape
  for a demo, and it is worth saying which one you are looking at.
- **Placeholders are a convention, not magic.** Four dialects are recognised without
  configuration — `<your-namespace>`, `{{ namespace }}`, `$NAMESPACE`, `SERVICE_HERE` —
  and a bare capitalised `NAMESPACE` deliberately is not, because that could be a real
  resource and a convention that swallows real names reports every estate as clean. A team
  spelling them another way adds theirs to `placeholder_patterns` in
  [`config/mappings.yaml`](config/mappings.yaml).
- **Label filtering costs one extra call per page** because CQL search is unreachable with
  a scoped token ([BUGS.md](BUGS.md) item 2). On a very large space that dominates a sweep.
- **The wording layer is not deterministic, and the checker is.** The same batch of five
  passages returned usable replacements for 1/5, then 4/5, then 4/5. `rr propose` retries
  only what still lacks wording, so re-running converges, but any measurement of *that*
  layer needs several runs. The finding, the evidence and the decision are deterministic;
  only the sentence is not.
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
  negative/        runbooks that are TRUE, where any finding is a false positive
docs/              measurement raw data
```

Further reading, in the order it is worth reading: [BUGS.md](BUGS.md) (what the APIs
actually did), [PROGRESS.md](PROGRESS.md) (every judgement call and its reasoning).

---

## Credit

Built by Vinayak (GitHub: [CulturalProfessor](https://github.com/CulturalProfessor)) for
the SuperDocs task.

The SuperDocs client and the test stub are copied from
`use-cases/CulturalProfessor/product-manual-builder` in this repository — same author,
same MIT licence — with provenance noted at the top of each file.
