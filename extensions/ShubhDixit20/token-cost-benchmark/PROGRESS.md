```md
# PROGRESS.md

Assumptions and decisions, logged as I went (per the brief: "a logged
assumption counts in your favor"). I used Claude heavily while scaffolding
and iterating on the harness — disclosed here and in the submission form's
AI-use question.

1. **Real-API validation is complete.** The benchmarking harness uses a
   `BaseClient` abstraction with two implementations: `MockClient` for
   deterministic offline testing and `SuperDocsClient` for the real REST API.
   The real client covers the four documented endpoints — upload, chat, approve,
   and export — including the double-JSON-parse behavior described in the API
   documentation. I have now run the benchmark in real mode against the live
   SuperDocs API and confirmed that the client works with the actual response
   format. The results in `data/results/` include benchmark output from the
   harness, with the README explaining how the runs were performed. The main
   remaining item is updating the illustrative pricing values in `metrics.py`
   with SuperDocs' actual per-model pricing so that cost calculations use the
   real rates.

2. **Token counting heuristic.** `tiktoken` was not available in the offline
   environment, so the mock arm and pre-flight estimates use the standard
   ~4-characters-per-token approximation. This is documented in `metrics.py`.
   For real API runs, the client uses the `usage.input_tokens` and
   `usage.output_tokens` returned by the API instead of relying on the
   estimate.

3. **"1 page ≈ 500 words."** This is a sizing convention rather than a measured
   constant. I use it only to generate the different corpus size tiers. The
   assumption is documented in `corpus.py` rather than being left as an
   unexplained constant.

4. **Domains covered.** The synthetic corpus currently covers vendor
   contracts, project status reports, and insurance claims — three of the four
   example domains in the brief. Clinical paperwork is not included at the
   moment. Adding another domain only requires adding it to the `DOMAINS` list
   in `corpus.py`.

5. **"Insert" edit type in the section-edit arm.** An "insert a new section"
   instruction doesn't map directly to replacing an existing section body.
   For the benchmark, I model it as adding the new content to the targeted
   section's body instead of actually increasing the number of sections. This
   likely underestimates the cost and complexity of a true section insertion
   in the product. The limitation is also called out in the README.

6. **Budget guard granularity.** The budget check happens after each edit. If
   the next edit would take the run over the limit, the runner stops before
   starting that edit. This means the final spend can exceed the configured
   budget by at most the cost of one edit. Partial results are written before
   raising `BudgetExceeded`, rather than discarding the run.

7. **Pricing constants in `metrics.py` are illustrative placeholders.** They
   are kept in a simple dictionary so that replacing them with SuperDocs'
   actual per-model pricing only requires changing configuration rather than
   the benchmark logic.

## What's built (as of this log)

- [x] Corpus generator, 5 size tiers, 3 domains, deterministic
- [x] Multi-turn edit-session generator, 5 edit types
- [x] Mock client (offline, deterministic) + real `SuperDocsClient`
- [x] Real API validation using the live SuperDocs API
- [x] Whole-doc arm and section-edit arm, with cost/token/time/chars-sent
      recorded per edit
- [x] Runner: small-sample mode, budget guard with a hard stop, repeats for
      variance, raw CSV/JSON output
- [x] Report generator: summary tables (overall, by tier × arm, variance),
      cost-vs-size chart, cumulative-session-cost chart
- [x] Offline test suite (corpus, arms, metrics, runner) — 22/22 passing,
      no live key needed
- [ ] Replace illustrative pricing values with SuperDocs' actual per-model
      pricing
- [ ] PR into `github.com/superdocsapp/superdocs-builds` under `extensions/`
```
