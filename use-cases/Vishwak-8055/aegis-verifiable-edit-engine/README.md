# Aegis

**A verification layer for AI-powered document edits.** Aegis sits between "an AI proposed this edit" and "this edit is now in the document", and answers one question with evidence instead of a shrug: *did this edit stay in scope and leave everything it wasn't supposed to touch alone?*

```
$ npm run demo
```
turns into a real, unstaged verdict — not a mockup:
```
--- Attempt 1 — unsafe rewrite (with an injected reference doc + attempted policy downgrade) ---
✗ VERIFICATION FAILED

Highest-severity finding: SEMANTIC_OBLIGATION_TO_PERMISSION (CRITICAL, semantic)
Before: "The Supplier shall deliver the goods within 30 days of the order date."
After:  "The Supplier may deliver the goods within 30 days of the order date."

Decision: BLOCKED
The document was not committed. (receipt status: rejected)
```

## Why this exists

An AI editor (SuperDoc's agent tooling, a custom LLM pipeline, anything that proposes DOCX changes) can make a document *read* better while quietly changing what it *means* — a `shall` softened to a `may`, a `30 days` stretched to `60`, a `except in the case of breach` carve-out that just isn't there anymore. None of that looks wrong in a diff of the prose. It's wrong in the specific, structured sense of "the deal changed and nobody agreed to that."

Aegis's job is narrow on purpose: given a `before`, an `after`, and the instruction that supposedly produced it, decide — with evidence, not a vibe — whether the result actually matches what was asked, and produce an `EditProof` that says exactly what was checked, what changed, and why the decision came out the way it did.

## What's real here, and what isn't

This is a from-scratch, standalone implementation — there was no pre-existing SuperDocs repository, Task 1/Task 2 code, or SuperDoc API credentials available while building it (see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#superdoc-integration) for what was actually checked and cited). Everything below is genuinely implemented and exercised by real, executed tests:

- The full verification pipeline: intent compilation → six independent checkers → risk scoring → decision → bounded recovery → `EditProof`.
- A deterministic **mock** SuperDoc adapter, clearly labeled as such everywhere it appears — no network calls, no credentials, safe to run in CI.
- 101 automated tests (unit, integration, adversarial, property) and a 21-case adversarial benchmark, all runnable with the commands below, none of them hard-coded to pass.
- A real, accessible verification UI (`ui/index.html`) with an automated structural-accessibility check (axe-core, 0 violations) and manually-verified color contrast.

What's **not** implemented: a live SuperDoc client (real SuperDoc is a self-hosted, client-side DOCX engine with no SaaS API — see the architecture doc for what a real adapter would need), a REST service layer, and a wired-up LLM provider for the optional semantic-ambiguity hook. These are documented, designed-for extension points, not silent gaps — see [Known limitations](docs/ARCHITECTURE.md#known-limitations).

## Quickstart

```bash
npm install
npm run typecheck   # tsc --noEmit
npm run lint        # eslint
npm test            # unit + property tests (vitest)
npm run integration-test   # integration + adversarial tests
npm run benchmark   # runs benchmark/dataset.ts through the real pipeline, prints real metrics
npm run demo        # the end-to-end scenario shown above
npm run ui-test     # functional + accessibility smoke test for ui/index.html
```

Then open `ui/index.html` directly in a browser (no server needed — the demo's real output is embedded in it) to see the verification report, or run `npm run demo` first to regenerate `ui/sample-proofs/*.json` from a fresh run.

No environment variables are required for any of the above — everything runs in mock mode by default. See [`.env.example`](.env.example) for what a live deployment would configure.

## Repository layout

```
src/
  types/          Shared types: AegisDocument, CompiledIntent, Severity/Finding/Decision
  intent/         Intent Layer — scope + invariant extraction, the optional AI hook
  verification/   The six checkers, the block aligner/normalizer, the suite runner
  risk/           Severity policy (data-driven, see policy.default.json) + decision engine
  execution/      SuperDocClient interface + the deterministic mock implementation
  recovery/       Bounded, fully-re-verified retry loop
  evidence/       EditProof model, canonical serialization, hashing, secret redaction
  orchestrator/   AegisEngine — the single public entry point wiring it all together
  config/ logging/
bin/demo.ts       The end-to-end demo (brief section 24's scenario)
benchmark/        Adversarial benchmark dataset + runner
test/             unit / integration / adversarial / property
ui/index.html     Standalone verification UI (open directly, no build step)
docs/             Architecture, EditProof schema, security, this file's longer siblings
```

## Where to go next

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — layers, data flow, the risk model's rationale, SuperDoc integration, known limitations, extension points.
- [`docs/EDITPROOF_SCHEMA.md`](docs/EDITPROOF_SCHEMA.md) — field-by-field reference, with a real example.
- [`docs/SECURITY.md`](docs/SECURITY.md) — prompt-injection resistance, secret handling, what's deliberately *not* trusted.
- [`docs/BENCHMARK.md`](docs/BENCHMARK.md) — what the 21 cases cover and how to read the results.
- [`CHANGELOG.md`](CHANGELOG.md).
