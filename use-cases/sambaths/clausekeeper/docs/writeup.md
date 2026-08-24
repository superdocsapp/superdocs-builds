# clausekeeper — ISO 9001:2015 traceability over a SuperDocs session

## What & for whom

Quality managers inherit a quality manual plus five procedures that never quite prove coverage. Clausekeeper keeps those six documents in one SuperDocs multi-document session, maps every ISO 9001:2015 clause to the sections that cover it with provenance (`chunk_id`, heading path, verbatim quote), re-checks when procedures are edited, and raises orphaned clauses as gaps naming the exact edit (`change_id`, instruction, job, time).

## Measured

Every number below comes from a committed run output or test assertion — never estimated. Paths are relative to `use-cases/sambaths/clausekeeper`.

| Measure | Result | Trace |
|---|---|---|
| Keyless test suite | **46 passed** in ~10 s | `EVIDENCE.md:10` and `docs/media/transcripts/clausekeeper-b6-pytest.txt` |
| Full demo cycle | **9 billable ops** (≤10 gate) | `docs/media/transcripts/clausekeeper-b1-gap.txt` (init 0 + link 6 + edit 1 + show) + `docs/media/transcripts/clausekeeper-b3-pack.txt` (pack 1 + exports free) = 9; `EVIDENCE.md` usage ledger |
| Pack generation + exports | **1 op** for generation, DOCX + PDF via pre-signed downloads, `X-Export-Warnings` checked | `docs/media/transcripts/clausekeeper-b3-pack.txt` (`ops_spent:1`, `warnings:["font Calibri substituted on page 2"]`) and `tests/fixtures/pack_flow.json` |
| Discover lane free-read | **12/27** linkable clauses shortlisted at **0 ops** | `docs/media/transcripts/clausekeeper-b4-discover.txt` (`local match resolved 12/27 ... (0 ops)`) and `tests/test_discover.py` |
| Discover lane batched search | **one turn, +1 op** capped, 15 remaining clauses via search | `docs/media/transcripts/clausekeeper-b4-discover.txt` (`[search] charged 1 op`, `search resolved 15/15`) and `tests/fixtures/discover_link.json` |
| Discover plan preview | **0 ops** | `docs/media/transcripts/clausekeeper-b4-discover.txt` (`DISCOVER PLAN (preview mode - zero billable ops)` and `projected search spend: 1 op`) |
| Discover weak fallback | **WARN fallback at 1 op**, no fabricated candidates | `docs/media/transcripts/clausekeeper-b4-weak.txt` (`WARN: search returned usable candidates for only 0 of 15 unresolved clauses`, `WARN: discover could not shortlist 15 clauses - continuing with standard mapping`) and `tests/fixtures/discover_weak.json` |
| Gap lands on approve | `chg_42` at `2026-08-22T14:02:00Z`, instruction `Delete the disposition section`, job `job_edit_01` | `docs/media/transcripts/clausekeeper-b1-gap.txt` and `tests/fixtures/edit_delete.json` |
| Rename survival | `durable_document_id` matrix intact after `NM-PRO-04` → `NM-PRO-04-v2` | `docs/media/transcripts/clausekeeper-b2-rename.txt` and `tests/test_guards.py::test_rename_keeps_links_and_refreshes_display_name` |
| Seeded gaps detected | **2/2** (9.2 Internal audit, 7.4 Communication) | `docs/media/transcripts/clausekeeper-b1-gap.txt` (`seed SEED-H1 clause 9.2: DETECTED`, `seed SEED-H2 clause 7.4: DETECTED`) and `corpus/northgate/expected-gaps.yaml` |

## Why trade-offs

- SQLite matrix keyed on `durable_document_id` → renames survive display-name churn → single-writer, no concurrent editors; acceptable for a QMS control room
- One compact verification turn per document (`1 op/doc`) → costs stay predictable → slower gap surfacing within a cycle vs per-clause calls
- Free structural reads + at-most-one batched search for Discover → honors op budget → search precision limited by heading phrasing; advisory only
- Local gap-landing on `chunk_id` delete/edit → synchronous attribution (`chg_42` narrative) → only covers sections that were previously linked; new uncovered clauses rely on `show`
- Template upload once, pack generation one turn, pre-signed `DOCX` + `PDF` exports free via `POST /v1/downloads` with `X-Export-Warnings` decoded → branded output without per-page ops → export warnings are advisory, not blocking
- Fixture-replay tests (`tests/fixtures/*.json`) → fully keyless, deterministic, stranger-runnable → live lane still hand-verified, not simulated

## Honest limitations

Keyless tests mean the live path was verified by hand, not in CI; readiness statements cover the ISO 9001:2015 clause *structure* only — not an audit, they grant no standing and no external body has reviewed them; verification quality depends on the model tier behind the session; gaps can be false positives until a human reviews them at the approval flow.

Live-test note (2026-08-23, from `scratch/issues/assets/0006-live-uat-discover.md`): `free-read works at 0 ops, batched search exceeded 300 s and fabricated candidate on seeded-gap 9.2` — worse than plain mapping on honesty. The free-read lane completed live at 0 ops for five local clauses; the single batched search turn exceeded SuperDocs documented `verification_turn` max-wait (`300 s`), the CLI aborted before mapping and no shortlist rows persisted, and the model returned a plausible-looking section for seeded-gap clause 9.2 where no covering document exists by design. The later rerun completed within the envelope at 0 ops but returned zero usable candidates with honest `WARN` fallback — shortlists remain advisory only, nothing feeds the mapping turns automatically, and every search-sourced row should be treated as unverified until a human checks it. See also `docs/media/transcripts/clausekeeper-b4-weak.txt` for the honest WARN path on film.

## What's next

In order, each with what gets dropped: **(1)** surgical edit contract — outline-anchor edits with numbering-matches-placement validation, refuse placeholder tables where the document already contains the field (drop auto-styling normalization); **(2)** job observability — live progress events, structured errors everywhere, resumable sessions (drop synchronous blocking endpoints for large docs); **(3)** Google Docs add-on first — read via host API, edit via four calls, write back range-by-range (drop import-format breadth for a quarter); **(4)** a public document-editing benchmark — SWE-bench for documents, doubling as the regression harness (drop model-provider optionality breadth).

## Run it yourself

`use-cases/sambaths/clausekeeper` on `superdocs-builds` PR #137 (`clausekeeper-core`), commit `04257bb`.

```bash
pip install -r requirements.txt
python -m pytest -q  # → 46 passed in ~10 s (fixture-replay, no API key) — see docs/media/transcripts/clausekeeper-b6-pytest.txt
python -m clausekeeper --fixture tests/fixtures/init_link.json init
python -m clausekeeper --fixture tests/fixtures/init_link.json link
CK_AUTO_APPROVE=1 python -m clausekeeper --fixture tests/fixtures/edit_delete.json edit NM-PRO-04 --instruction "Delete the disposition section"
python -m clausekeeper --db /tmp/ck-b1.db show  # gap chg_42 with durable_document_id — see docs/media/transcripts/clausekeeper-b1-gap.txt
python -m clausekeeper --fixture tests/fixtures/pack_flow.json --db /tmp/ck-pack.db pack --template assets/northgate-letterhead.docx --out /tmp/ck-exports  # 1 op + X-Export-Warnings — see docs/media/transcripts/clausekeeper-b3-pack.txt
python -m clausekeeper --fixture tests/fixtures/discover_link.json link --discover  # free-read 12/27 at 0 ops + one batched search 15 rows at 1 op — see docs/media/transcripts/clausekeeper-b4-discover.txt
python -m clausekeeper --fixture tests/fixtures/discover_link.json link --plan --discover  # 0 ops
python -m clausekeeper --fixture tests/fixtures/discover_weak.json link --discover  # WARN fallback — see docs/media/transcripts/clausekeeper-b4-weak.txt
```

This video is fully agent-generated with synthetic narration (Kokoro TTS `am_eric`, open-source) — no human on camera.
