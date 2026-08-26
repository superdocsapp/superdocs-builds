# Security — Phase 8 Hardening

## Source documents are untrusted data

Contracts arriving through this pipeline are treated as **data to analyze,
never as instructions to execute**. Nothing in the deterministic analysis
path (`src/pipeline.py::analyze_contract`, `src/rules/`, `src/extraction/`)
is an LLM call that could be talked into a different decision by document
content — eligibility, rate extraction, and notice-sufficiency are all
regex/rule-based functions over the raw text. A contract cannot alter this
system's *behavior* by embedding text, no matter how it's phrased.

The one place raw document text legitimately flows into an external-facing
string is `build_instruction()` (`src/amendment_case.py`): the pricing
clause's heading (extracted verbatim as `clause_reference`) is interpolated
into a fixed template sent to SuperDocs. Even a hostile heading only ever
appears **quoted** inside that template's own imperative sentences ("update
ONLY the rate table...", "Do not add, remove, or reword any other
clause...") — the app does not parse or execute anything from the resulting
string; it is forwarded to SuperDocs as one scoped, template-controlled
instruction specifying literal destination/rate pairs already computed by
`src/rate_diff.py`, not by reading the contract's prose. See
`tests/security/test_prompt_injection_resistance.py::test_injection_via_forged_clause_heading_stays_quoted_never_executed`.

**Detection vs. enforcement.** `src/rules/conflicts.py::has_prompt_injection`
flags common injection phrasings ("AI assistant: ...", `SYSTEM:`/`USER:`
framing, "ignore previous instructions", "disregard the above") as a
`Conflict` fact, which forces `eligibility.status` to `REQUIRES_REVIEW` (a
human must resolve it) — this is a **best-effort audit signal for
reviewers**, not the security boundary itself. The actual guarantee is
structural: nothing downstream *interprets* contract text as a directive,
regardless of whether the regex catches a given phrasing. A contract engineered
to evade the regex still cannot flip eligibility, alter a rate, or trigger an
auto-approval — see `tests/security/test_prompt_injection_resistance.py`.

## Secret handling

- `SUPERDOCS_API_KEY` is read once from the environment
  (`src/integrations/superdocs_client.py::_api_key`) and sent only as the
  `Authorization: Bearer ...` header on outbound SuperDocs calls — never
  logged, persisted, or echoed back in any API response.
- `.env` is gitignored (`.gitignore`); `.env.example` documents the required
  variables (`SUPERDOCS_API_KEY`, `DATABASE_URL`, `AGENT_API_PORT`) without
  real values. Copy it to `.env` and fill in real credentials locally —
  never commit `.env`.
- No logging infrastructure exists in `src/` yet. `src/integrations/redaction.py`
  provides `redact_headers()` — masks `Authorization`, `X-Api-Key`, `Cookie`,
  and `Set-Cookie` case-insensitively — ready to wire in the moment any
  logger is introduced. **Any future logging of request headers, `httpx`
  request/response objects, or raw error bodies MUST pass through
  `redact_headers()` first.** `SuperDocsError.likely_cause` sometimes embeds
  `response.text[:500]` (the SuperDocs *server's* response body, not request
  secrets) — still worth reviewing before adding it to any log sink, since a
  server error page could echo back request details.
- CI runs a secret-scanning step (`.github/workflows/ci.yml`, `gitleaks`) on
  every push/PR to catch an accidentally committed key before merge.

## Authentication

The `src/api` FastAPI app (port 8100) has **no caller authentication** —
this is a gap, not a design choice, and matches its current intended use as
an internal/dev-only service (permissive CORS restricted to
`localhost:5174`, per `src/api/main.py`). Before exposing this API beyond a
local/internal network, add an auth dependency (API key or JWT) to every
route in `src/api/routes/`.

## Approval-gated commits

`POST /documents/{event_id}/decide` (`src/incremental.py`,
`src/persistence/document_registry_repo.py`) is the only path that commits a
document's proposed state as the new `prior_contract_state` — enforced with
a `WHERE approval_decision IS NULL` guard so a decision can be recorded
exactly once per event (`AlreadyDecided` → 409 on a second attempt,
regardless of whether the retry repeats or reverses the decision). See
`docs/RELIABILITY.md` for the concurrency angle on this same guard.
