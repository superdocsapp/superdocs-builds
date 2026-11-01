# EditProof schema

Type definition: `src/evidence/editProof.ts` (`EditProof` interface). Builder: `buildEditProof()` in the same file. Two complete, real, generated examples (not hand-written) live in `docs/examples/`:

- [`example-editproof-blocked.json`](examples/example-editproof-blocked.json) — the demo's unsafe rewrite, `decision: "BLOCKED"`.
- [`example-editproof-verified.json`](examples/example-editproof-verified.json) — the demo's safe rewrite, `decision: "VERIFIED"`.

Both were produced by `npm run demo` against the mock adapter, then copied verbatim — nothing in them was edited by hand.

## Top-level fields

| Field | Type | What it answers |
|---|---|---|
| `proof_version` | `string` | Schema version (`"1.0.0"`). Bump this if the shape below changes. |
| `operation_id` | `string` | Correlation id for this run (a UUID by default; injectable for tests — see `AegisEngineDeps.idGenerator`). |
| `timestamp` | `string` (ISO 8601) | When the proof was issued. |
| `intent` | object | *What did the system understand it was asked to do?* — `instruction_text`, `summary`, `edit_kind`, `scope`, `confidence` (0–1), `ai_assisted` (always `false` in this build — see `NullAiProvider`). |
| `scope` | `ScopeSpec` | The resolved scope used for verification (same shape as `intent.scope`; kept top-level too since scope is referenced by several other sections). One of `whole-document`, `style-only`, `paragraph-index` (+`index`), `heading` (+`headingText`), `unscoped`. |
| `changed_regions` | `RegionEvidence[]` | *What did it actually change?* — one entry per non-`unchanged` alignment result, each with `kind` (`modified`/`inserted`/`deleted`), block ids, and excerpts (capped at 220 characters — see `EXCERPT_LIMIT`). |
| `unchanged_regions` | `RegionEvidence[]` | *What stayed the same?* — the complement of the above; same shape, `kind: "unchanged"`. |
| `protected_invariants` | `InvariantEvidence[]` | Eight human-facing groups (numbers, dates, currency, links, obligations, structure, scope, formatting), each `{ key, label, passed, violating_finding_ids }`. This is what the UI's invariant checklist renders directly — see `INVARIANT_GROUPS` in `editProof.ts` for the exact finding-kind membership of each group. |
| `verification_results` | `VerificationResultEvidence[]` | One entry per checker (always 6: structural, protected_value, semantic, scope, formatting, drift) — `{ checker, passed, finding_count, duration_ms }`. `passed` means no finding from that checker reached `MEDIUM` or above. |
| `drift_results` | `{ kind, message }[]` | The drift checker's findings only (a subset already present in `evidence.findings`), surfaced separately since it's explicitly a named schema field in the brief. |
| `risk_assessment` | object | `{ highest_severity, counts }` — `counts` is a complete `{INFO,LOW,MEDIUM,HIGH,CRITICAL}` tally, always present even when every count is `0`. |
| `decision` | `Decision` | `"VERIFIED" \| "VERIFIED_WITH_WARNINGS" \| "REQUIRES_REVIEW" \| "BLOCKED"` — see `src/risk/decisionEngine.ts`. |
| `evidence` | object | The full, unsummarized trail — see below. |
| `execution_metadata` | object | Operational facts about the run — see below. Passed through `redact()` before the proof is assembled, so it's safe to log or store as-is. |

## `evidence`

| Field | Type | Notes |
|---|---|---|
| `proof_hash` | `string` | A content fingerprint (`stableHash`, `src/evidence/hash.ts`) over the entire proof *except this field*. Recomputing it the same way (strip this field, hash the rest) against a stored proof should reproduce the same value — that's the tamper-evidence property `test/integration/pipeline.test.ts` checks. It is **not** a cryptographic hash — see the doc-comment in `hash.ts` for why that's a deliberate, documented tradeoff, and what to swap in if a deployment needs one. |
| `findings` | `ClassifiedFinding[]` | Every finding from every checker, with `severity` and `recoverable` already resolved by policy. This is the actual source of truth — `protected_invariants`, `verification_results`, and `drift_results` are all views over this same array. |
| `attempts` | `RecoveryStepRecord[]` | One entry per `proposeEdit` call (see [Recovery](ARCHITECTURE.md#recovery-behavior)), `{ attempt, instructionUsed, decision, highestSeverity, findingCount }`. Length `1` unless a retry happened. |
| `rejected_policy_overrides` | `RejectedOverride[]` | Non-empty only when the caller's `policyOverride` tried to downgrade a non-downgradable finding kind — see [docs/SECURITY.md](SECURITY.md). Empty in the vast majority of runs. |

## `execution_metadata`

| Field | Type | Notes |
|---|---|---|
| `superdoc_mode` | `"mock" \| "live"` | Always `"mock"` in this repository — see [Known limitations](ARCHITECTURE.md#known-limitations). |
| `session_id` | `string` | The adapter's session identifier. |
| `adapter_operation_id` | `string` | The adapter's own id for the final accepted/rejected operation. |
| `final_receipt_status` | `"applied" \| "rejected" \| "pending"` | What actually happened to the tracked change — `pending` only for `REQUIRES_REVIEW`. |
| `duration_ms` | `number` | Wall-clock time for the whole `runEdit()` call, including every retry. |
| `checker_durations_ms` | `Record<string, number>` | Per-checker timing from the *final* verification run, for the performance review pass (brief section 31, Pass 5). |
| `retry_budget` | `number` | The configured `AEGIS_RETRY_BUDGET` for this run. |
| `attempts_used` | `number` | How many `proposeEdit` calls actually happened (`1` to `1 + retry_budget`). |

## A note on `timestamp` / `duration_ms` and hashing

Two separate `runEdit()` calls with identical logical inputs will **not** produce the same `proof_hash`, because each carries its own real `timestamp` and `duration_ms` — and that's intentional, not a bug: each call is a distinct real-world event, and an audit fingerprint that ignored *when* something happened would be a weaker one. What the hash guarantees is that a given, already-issued proof hasn't been altered since — see the tamper-evidence test referenced above.
