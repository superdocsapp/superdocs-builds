# EVIDENCE — every number here traces to a named test or committed run output

Nothing on this page is asserted. Each row names the test, script, or run
artifact you can check yourself — all keyless, all runnable by a stranger.

## Keyless suites (run them)

| Claim | Measured | Trace |
|---|---|---|
| clausekeeper test suite is green and keyless | **46 passed** in ~10 s | `use-cases/sambaths/clausekeeper/` @ commit `04257bb` (clausekeeper-core, pushed HEAD); run: `python -m pytest -q` (fixture-replay transport, no API key) |
| Task 1 engine suite is green and keyless | **59 passed** in ~45 s | `doctask-sambaths` @ commit `8be5426` (main, pushed HEAD); run: `python -m pytest -q` (keyless) |

## Durability proofs (behavior tests, keyless)

| Claim | Measured | Trace |
|---|---|---|
| kill -9 mid-stage resumes with byte-identical results, zero duplicated work | units **105 == 105** vs fresh control · LLM calls **87 == 87** · `duplicate_llm_keys=[]` | `tests/task1/test_f1_kill9_midstage_resume.py`; resume committed revision `rev-1964063d471f` |
| arrival-driven update touches only affected sections | only `schedule` hash changed `9ebca232 → 240b2bb0`; other 4 sections byte-identical; empty-text PDF skipped with no new revision | `tests/task1/test_arrival_conflict_fresh_item.py` + UAT replay record |

## One core, three surfaces

| Claim | Measured | Trace |
|---|---|---|
| REST ⇄ MCP drive the same gate state | parity by construction — shared service layer, proven by twin-database state-diff test | `tests/surface/test_mcp_server.py` |
| REST ⇄ MCP ⇄ UI produce the same revision id | all three paths committed **`rev-1964063d471f`** | MCP-drive UAT + browser UI session records; five-tool MCP server exercised by `scripts/machine_drives_gate.py` / `tests/surface/test_machine_drives_gate.py` |

## Op economy (billed ops from real usage fields)

| Claim | Measured | Trace |
|---|---|---|
| full clausekeeper demo cycle fits the ≤10-op gate | **9 billable ops**, `monthly_remaining` tracked throughout | usage ledger written per billable run (ticket-recorded UAT step 5, 2026-08-23) |
| extra-credit weekly mode full pass costs one op | small-sample **0 ops**, full pass **1 op** | `docs/media/transcripts/weekly-usage.json` (tracked ledger copy, `doctask-sambaths` @ pushed main) — raw data committed beats reproduce-by-command |

## Honesty notes

- One parallel-commits test (`test_f4_same_pile_twice.py::test_behavior9_…`) previously flaky (90 s timeout vs 1 s pass) — deflaked 2026-08-24 via bounded retry and WAL stagger; verified **59 passed** at `8be5426` (10/10 solo, 3/3 full suite in ~45 s).
- Readiness statements are assessments against the ISO 9001 clause structure,
  not legal advice; verification quality depends on the model tier behind the
  session.
