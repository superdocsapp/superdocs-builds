# PROGRESS.md

Assumptions and decisions, logged as I went (per the brief: "a logged
assumption counts in your favor"). I used Claude heavily to scaffold this
harness — disclosed here and in the submission form's AI-use question, not
hidden.

1. **Real-API validation is still outstanding.** The harness was built and
   unit-tested with a `BaseClient` abstraction: `MockClient` (deterministic,
   offline — what the committed tests and `data/results/` currently use) and
   `SuperDocsClient` (real REST calls to the four documented endpoints —
   upload, chat, approve, export — including the documented double-JSON-parse
   gotcha). **The numbers currently committed in `data/results/` are from
   mock mode, not the real API** — stated plainly in the README results
   section rather than presented as measured product cost. Before I call this
   done I still need to: (a) sign up and use SuperDocs by hand per "Getting
   Started", (b) run `--mode real --small-sample` against my own API key to
   prove the real client actually matches the live API's response shape,
   (c) replace the pricing constants in `metrics.py` with SuperDocs' real
   per-model pricing instead of the illustrative numbers currently there.

2. **Token counting heuristic.** No `tiktoken` install available (offline).
   Used the standard ~4-chars/token approximation for the mock arm and for
   pre-flight estimates, and documented it as an approximation in
   `metrics.py`'s docstring. When running against the real API, real
   `usage.input_tokens`/`usage.output_tokens` from the response are used
   instead — the estimator is a fallback, not the source of truth for real
   runs.

3. **"1 page ≈ 500 words."** Not a measured constant, just a common
   convention, used only to size the synthetic corpus into tiers. Logged in
   `corpus.py`'s module docstring rather than left as an unexplained magic
   number.

4. **Domains covered.** Synthetic vendor contracts, project status reports,
   and insurance claims — three of the four example domains the task brief
   names (I left out clinical paperwork; nothing in my corpus generator
   assumes a specific one, so adding a fourth domain is a config change in
   `corpus.py`'s `DOMAINS` list, not a rewrite).

5. **"Insert" edit type in the section-edit arm.** An "insert a new section"
   instruction doesn't cleanly fit "replace one section's body" — I model it
   as appending the new content to the targeted section's body rather than
   growing the section list. This underestimates the real cost/complexity of
   a true insert in the actual product. Flagged here and in the README
   limitations, not smoothed over.

6. **Budget guard granularity.** The guard checks cumulative spend *after*
   each edit and stops before starting the next one — so a run can overshoot
   the cap by at most one edit's cost, never more. I chose to write partial
   results on trip rather than discard them (`_write_results` is called
   before the `BudgetExceeded` is raised).

7. **Pricing constants in `metrics.py` are illustrative placeholders**, kept
   in a plain dict specifically so plugging in SuperDocs' real per-model
   pricing later is a data change, not a code change (per "configuration
   over code").

## What's built (as of this log)

- [x] Corpus generator, 5 size tiers, 3 domains, deterministic
- [x] Multi-turn edit-session generator, 5 edit types
- [x] Mock client (offline, deterministic) + real SuperDocsClient (code
      written against the docs, not yet validated live — see item 1)
- [x] Whole-doc arm, section-edit arm, both with cost/token/time/chars-sent
      recorded per edit
- [x] Runner: small-sample mode, budget guard with a hard stop, repeats for
      variance, raw CSV/JSON output
- [x] Report generator: summary tables (overall, by tier×arm, variance),
      cost-vs-size chart, cumulative-session-cost chart
- [x] Offline test suite (corpus, arms, metrics, runner) — 22/22 passing,
      no live key needed
- [ ] Real-API validation run against my own SuperDocs key
- [ ] PR into github.com/superdocsapp/superdocs-builds under extensions/