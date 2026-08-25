# doctask2 — Spec-Driven Client Generation Pipeline

Consumes SuperDocs' **published OpenAPI spec** and, in one command, produces
typed API clients for **Python** and **TypeScript**, a **compatibility report**
between two spec versions (with a CI gate that fails on breaking changes), and a
**smoke test per language** against a mock server — no API key, no live service.

---

## What this is & who it serves

When an API is defined by a spec, the clients, the change-review, and the tests
should all be **generated from that spec**, not hand-maintained. This pipeline is
for the team that owns the SuperDocs API and the developers who consume it:

- **API owners** get an automated **breaking-change gate** — a PR that changes
  the spec incompatibly fails CI before it ships.
- **Client developers** get **typed SDKs** (Python + TypeScript) regenerated
  from the spec, and proof they actually work (smoke tests against a mock).

## One-command run

```bash
make all          # fetch → generate → compat (gate) → mock → smoke
```

Requirements: **Docker** (runs the generator, differ, and mock — so a clean
machine needs nothing else installed), plus **python3** and **node** to run the
two smoke tests. No API key. On Windows without `make`, run `bash scripts/pipeline.sh`.

What it does, in order:

| Stage | Tool | Output |
|---|---|---|
| Fetch | `curl` (pinned commit SHAs) | `specs/superdocs-old.json`, `superdocs-new.json` |
| Generate | **openapi-generator 7.12** (Docker) | `clients/python/`, `clients/typescript/` |
| Patch | `scripts/patch_generated.py` | real package metadata + SDK version from the spec |
| **Compat report** | **oasdiff** (Docker) + `scripts/compat.py` | `reports/compat.md` + `compat.json`, **CI gate** |
| Mock | **Stoplight Prism** (Docker) | mock server on `:4010`, schema-valid examples |
| Smoke | pytest (Py) + tsx (TS) | one typed call per client through the mock |

## Architecture — why each tool

- **openapi-generator** : it's the industry
  standard, supports 40+ targets, and turns "add a language" into a one-line
  config change. *Buys:* correctness + breadth for free. *Costs:* generated code
  is verbose and opinionated, and OpenAPI 3.1 support needs a recent version
  (we pin 7.12 and pass `--skip-validate-spec` because the published spec uses a
  few 3.1-only constructs).
- **oasdiff** (not a bespoke differ): purpose-built OpenAPI diff with a
  **severity model** — it already knows that a removed endpoint or a
  newly-required parameter is *breaking* while an added endpoint is *safe*. Our
  `scripts/compat.py` wraps its JSON output into a human report and the CI gate.
  *Buys:* correct breaking-change classification. *Costs:* one more binary
  (we run it via Docker so nothing is installed).
- **Stoplight Prism** (not a stub server): mocks the API straight from the spec,
  returning schema-valid example responses — so the smoke tests exercise the
  generated clients with **zero** hand-written server code and **no** API key.
- **Docker for all three**: the reproducibility guarantee. The images are pinned
  in the pipeline; a reviewer with Docker gets identical generator and diff
  behavior.

## Post-generation patches

`scripts/patch_generated.py` is intentionally the only patch step. It changes no
generated request, model, or transport code. It replaces OpenAPI Generator's
placeholder repository metadata in both packages and makes their package version
match `info.version` in the input spec. Scheduled releases add a deterministic
spec-hash suffix because a registry needs a unique version even when the published
spec changes without an API version bump. The script asserts the expected generated
shape, so a generator upgrade cannot silently make a patch apply incorrectly.

## The compatibility report (the centerpiece)

`scripts/compat.py` consumes oasdiff's JSON changelog and emits `reports/compat.md`
+ `reports/compat.json`, classifying every change as **breaking** (oasdiff level 3
— removed endpoint, newly-required param, narrowed type) or **safe** (added
endpoint, new optional field). With `--gate` it **exits non-zero on any breaking
change**, so CI fails on an incompatible spec bump.

**Result on the real SuperDocs history** (`old → new`, see below):

> **BACKWARD COMPATIBLE** — 0 breaking, 32 safe changes (12 endpoints added).
> Both specs declare version **2.0.0**, yet the contract changed. *The version
> string alone does not signal compatibility — this diff does.* That gap is the
> whole reason this report exists.

**Proving the gate actually fires:** the pipeline also diffs the new spec against
a synthesized breaking revision (`specs/superdocs-breaking.json`) and asserts the
gate returns non-zero. It flags exactly the three injected breaks:

```
request-parameter-became-required   POST /v1/chat            authorization became required
api-path-removed-without-deprecation POST /v1/documents/export path removed
request-parameter-type-changed      GET  /v1/documents/{id}   document_id string → integer
```

## Where the "previous" spec version came from

The task needs two spec versions to diff. **We used real published history, not a
fabricated one:**

- **New** = `superdocsapp/docs@ac0d44c` (2026-07-23), 77 paths.
- **Old** = `superdocsapp/docs@a8351de` (2026-06-24), 65 paths.

Both are the genuine `openapi.json` at those commits, pinned by SHA for
reproducibility. There are no version *tags* in the repo, but `openapi.json` has
25 commits of history — we picked two a month apart. Notably **both are labeled
`info.version: 2.0.0`** despite 32 structural differences, which makes the
version-diff genuinely useful.

The real diff turned out to be **backward-compatible** (only additions) — the
correct, honest result. So to demonstrate the breaking-change gate, we
**additionally** synthesize a breaking revision from the new spec via
`scripts/make_breaking_demo.py`, applying three controlled, clearly-logged deltas
(remove an endpoint, make a param required, narrow a type). This is the only
synthesized artifact; everything else is the real published spec.

## Repo layout

```
specs/          vendored spec versions (old, new) + synthesized breaking demo
clients/        generated Python + TypeScript clients (git-ignored; make all rebuilds)
reports/        compat.md + compat.json (the deliverable) + breaking-demo/
scripts/        fetch.sh, pipeline.sh, compat.py, make_breaking_demo.py, patch_generated.py
tests/          python/ (pytest) and typescript/ (tsx) smoke tests
mock/           (Prism runs from the spec directly)
/.github/workflows/              root CI + scheduled refresh/publish workflows
Makefile        one-command entry
```

## Explicit, defended cuts

Scoped as a one-day build. What we deliberately left out and why:

- **Registry publishing is credential-gated.** The scheduled root workflow
  detects a published-spec change, runs this pipeline, commits the refreshed
  specs and reports, then publishes Python to PyPI and TypeScript to npm. It
  requires `PYPI_API_TOKEN` and `NPM_TOKEN`; without them it fails rather than
  claiming a release succeeded. Normal PR CI never publishes.
- **Two languages** (Python + TypeScript). They prove the pattern; Go, Java, etc.
  are each a one-line `openapi-generator` target, not new engineering.
- **Smoke test, not full contract coverage.** Python proves typed response
  deserialization on `GET /v1/users/me`; TypeScript additionally sends the
  baseline upload -> chat -> approve -> export workflow. Exhaustively testing all
  paths is volume, not signal, for one day.
- **Mock-only, no live API.** Prism from the spec keeps the whole pipeline
  hermetic, keyless, and reproducible. No auth or integration against production.
- **Generated clients used as-is.** No hand-editing of generator output — that
  is the entire value of spec-driven generation.

## Secrets

None required — the pipeline is mock-only. `.env` and `*.key` are git-ignored;
nothing secret is committed.

## Attribution

Built for the SuperDocs task. Uses the publicly published SuperDocs OpenAPI spec
(`docs.superdocs.app/openapi.json`, mirrored at `github.com/superdocsapp/docs`).
