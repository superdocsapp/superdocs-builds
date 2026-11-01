# Changelog

## 0.1.0 — Initial implementation

First version of Aegis, built from scratch (no pre-existing SuperDocs repository, Task 1/Task 2 code, or SuperDoc credentials were available — see `docs/ARCHITECTURE.md#superdoc-integration`).

**Added**
- Intent Layer: deterministic scope + invariant extraction (`src/intent/`), with a documented-but-unwired `AiProvider` hook for genuinely ambiguous cases.
- Verification Layer: six independent checkers — structural, protected-value, semantic, scope, formatting, drift (`src/verification/`) — plus the canonical `AegisDocument` model and LCS-based block aligner they all share.
- Risk Layer: a data-driven severity policy (`src/risk/policy.default.json`) with an enforced non-downgradable guard, and a decision engine mapping risk to `VERIFIED` / `VERIFIED_WITH_WARNINGS` / `REQUIRES_REVIEW` / `BLOCKED`.
- Recovery Layer: a bounded, fully-re-verified constrained-retry loop (`src/recovery/`).
- Evidence Layer: a versioned, deterministic, secret-redacted `EditProof` (`src/evidence/`).
- Execution Layer: a `SuperDocClient` interface shaped after SuperDoc's real, documented Query→Target→Mutate→Receipt/tracked-changes contract, and a deterministic `MockSuperDocClient` (`src/execution/`).
- `AegisEngine` orchestrator wiring all of the above (`src/orchestrator/`).
- CLI demo (`bin/demo.ts`) reproducing the brief's exact end-to-end scenario, including a live prompt-injection / policy-downgrade attempt that is rejected.
- 21-case adversarial benchmark (`benchmark/`).
- 101 automated tests across unit, integration, adversarial, and property suites (`test/`).
- Accessible, standalone verification UI (`ui/index.html`) with an automated accessibility smoke test (`ui/smoke-test.mjs`, axe-core + jsdom).
- Documentation: `README.md`, `docs/ARCHITECTURE.md`, `docs/EDITPROOF_SCHEMA.md`, `docs/SECURITY.md`, `docs/BENCHMARK.md`, two real generated example proofs.

**Fixed during development** (kept here because a couple are genuinely instructive, not just noise)
- `SEMANTIC_ACTOR_CHANGED` was originally policy-classified `MEDIUM`, which let an obligation quietly reassigned to the other party pass as `VERIFIED_WITH_WARNINGS`; the adversarial benchmark caught it, and it's `HIGH` now.
- The textual-drift detector flagged 100%-of-a-single-paragraph-document as "excessive churn," which is vacuous on documents that small; it now only evaluates once a document has at least 4 blocks.
- A requested-value-change regex (`"extend the deadline to 60 days"`) matched only `"60"` instead of `"60 days"`, because a more general numeric alternative was tried before the more specific duration one in the same regex alternation; reordered so the more specific pattern wins.
- The `install` npm script was originally `"npm install"`, which recurses into itself forever. Removed — plain `npm install` needs no custom script.

**Known limitations** — see `docs/ARCHITECTURE.md#known-limitations` (no live SuperDoc client, no REST layer, no wired-up LLM provider, English/common-phrasing heuristics, no unit-conversion or backtranslation drift detection, common-case-only currency/date parsing).
