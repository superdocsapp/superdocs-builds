# Progress

## Session 1 — Phase 0 / Prompt 1 (Scaffold)

- Branch `kathans22/pitch-deck-narrative` cut from `main`.
- Commits pushed:
  1. `549ce17` chore: add gitignore and env example with placeholder key
  2. `0787cb3` chore: scaffold src/generator package modules
  3. `a1a3275` chore: add config, output and evidence directory structure
  4. `01926e4` chore: add pyproject with dependencies and python 3.12 target
- Check: `python -c "import generator"` → **PASS** (editable install).
- Note: `.gitignore` adjusted so `out/.gitkeep` and `state/.gitkeep` are trackable while generated contents stay ignored.

## Session 1 continued — Phase 1 / Prompt 2 (Manifest + product)

- `fb23868` feat(config): declare the nine-section deck manifest with weight and image tags
- `69c4ae4` feat(config): define the ClarityDocs product being pitched
- Manifest: 9 sections; shared = 1,4,9; vertical = 2,3,5,6,7,8; image_eligible = 6,8.
- `product.yaml` frozen after this prompt (ClarityDocs constant across verticals).

## Session 1 continued — Phase 1 / Prompt 3 (Vertical knowledge)

- `1e8fe81` feat(config): add legal vertical knowledge
- `3d00cd1` feat(config): add fintech vertical knowledge
- `c389166` feat(config): add healthcare vertical knowledge
- `4b5a695` feat(config): add edtech vertical knowledge
- Four packs present; typical_objection strings distinct (find-and-replace bar).
- Regulatory refs framed as orientation, not certification claims.

## Session 1 continued — Phase 1 / Prompt 4 (Manifest load + validate)

- `fb3f79f` feat(manifest): load deck manifest, product and vertical files
- `aa36297` feat(manifest): validate required fields and fail with the specific gap
- `load_validated()` PASS on real config; missing-field errors name the gap.
- Fifth vertical = new YAML only (glob `*.yaml`).

## Session 1 continued — Phase 1 / Prompt 5 (Divergence scorer)

- `7a46a9e` feat(divergence): add pairwise lexical-overlap scoring for two texts
- `aaf4c03` feat(divergence): score all vertical pairs per section and aggregate by weight
- `6bae9c4` docs(divergence): define and justify the divergence threshold
- Metric: word Jaccard. Thresholds: vertical mean < 0.40; any vertical section < 0.55.
- Shared sections reported, not gated. Noun-swap fixtures fail; substance pairs pass.

## Session 1 continued — Phase 1 / Prompt 6 (Phase 1 proof)

- `d4aafed` test(divergence): identical text scores maximum overlap
- `09ffebf` test(divergence): template-and-swap fixture scores high and is caught
- `b1f15a8` test(divergence): genuinely distinct text scores low (+ weight aggregation assertions)
- `tests/test_divergence.py`: 4 passed, no SuperDocs, no network.

---

## Phase 1 — DONE

**What Phase 1 proved (before any SuperDocs call):**

1. Config spine exists: 9-section manifest with `shared`/`vertical` + `image_eligible`, frozen ClarityDocs product, four vertical knowledge packs that are not noun-swaps.
2. Loader/validator fails loudly naming the specific missing field; adding a vertical is data-only.
3. Divergence is **measured**, not claimed — Build 2’s counterpart to Build 1’s core-hash.

**Threshold chosen and why:**

| Gate | Value | Why |
|---|---|---|
| `VERTICAL_MEAN_MAX` | **0.40** | Between genuine substance (~0.03–0.25 with shared product words) and template-and-swap (~0.70+). Mean vertical overlap must stay **below** 0.40. |
| `VERTICAL_SECTION_MAX` | **0.55** | One hot section (often Objection/Proof) fails the run even if other sections dilute the mean. |
| Shared sections | **not gated** | Product is held constant; high Opening/Overview overlap is expected and reported only. |

Do **not** loosen thresholds to pass weak packs — fix YAML / narratives instead.

**Proven by hand-made fixtures:**

- Identical texts → Jaccard **1.0**
- `"legal team"` vs `"compliance team"` otherwise identical → high overlap (**≥0.7**) and `evaluate_divergence` **fails** (caught)
- Distinct pain points → low overlap (**&lt;0.25**) and evaluation **passes**
- Three-vertical synthetic set → shared mean **1.0**, vertical mean below threshold, cell counts 3 shared / 6 vertical

**Next:** Phase 2 — MCP client (2-section batch + landed-check ported from Build 1), still respecting CLAUDE.md.

## Session 1 continued — Phase 2 / Prompt 7 (MCP client port)

- `504ae59` feat(mcp): connect to SuperDocs MCP with bearer auth and named errors
- `4769473` feat(mcp): add upload, chat, approve, export methods
- `d896862` feat(mcp): auto-split any request over the configured batch cap
- Image billing recorded in `docs/image-generation-billing.md` (next commit).
- Cap: `SUPERDOCS_CHAT_BATCH_CAP` (default 2). 9 sections → 5 sequential chat calls.

## Session 1 continued — Phase 2 / Prompt 8 (Double-parse + landed-check)

- `8b1c153` feat(mcp): add parse_proposed_changes double-parse helper
- `1bd6320` feat(mcp): add landed-check comparing pre- and post-edit section content
- `465b62a` feat(mcp): split-retry sections that failed to land
- `3fca179` test(mcp): confirm current 4-section batch behavior against the live API
- **Live probe finding:** 4-section batch **did land all 4** on 18 Aug 2026 (silent no-op from Build 1 **not** reproduced this run). Cap=2 + landed-check kept as safe default; see `evidence/batch-4-section-probe.md`.

## Session 1 continued — Phase 2 / Prompt 9 (Operations ledger)

- `113b49d` feat(ledger): record and persist per-step operations and wall time
- `d6dfb70` feat(ledger): idempotent skip by content key and small-sample limit
- Ledger: step/vertical/ops/wall time → `state/ledger.json`; `--limit`; `OPS_BUDGET_CAP` / `--ops-ceiling`.
- Phase 2 MCP+ledger spine complete for this session pack (Prompts 7–9).

## Session 1 continued — Phase 3 / Prompt 10 (Narrative generation · legal)

- `0169e30` feat(narrative): build the skeleton document from the deck manifest
- `45a4e79` feat(narrative): batched section fill from a vertical's knowledge file
- `1855882` feat(narrative): export a vertical narrative to markdown and docx
- `beb81bd` feat(narrative): charge ops per batch to the ledger
- Follow-ups: `201f071` BUG-001 · `b07dbb1` stricter landed-check · `2e94436` stronger fill instruction
- Legal run exports: `out/pitch-script-legal-claritydocs.md` + `.docx` (~5–10 ops depending on retries).
- Script notice present; not a slide file. Some sections still had leftover placeholders on first quality pass — caught after stricter landed-check (BUG-001).

## Session 1 continued — Phase 3 / Prompt 11 (Format guard)

- `bc1777e` feat(guard): assert exported filename and title carry no deck/slide signature
- `03c12da` feat(guard): assert the speaking-script disclaimer line is present
- `8dc4a88` feat(guard): block export on guard failure and name the failed check
- `7362e6d` test(guard): guard rejects a deliberately mistitled document
- `assert_not_deck` wired into `export_narrative_files` — failure deletes the file and raises `FormatGuardError` naming the check (`filename` / `title` / `disclaimer` / `export_path`).
- Live check: legal export **PASS**; mistitled title `"ClarityDocs Investor Pitch Deck"` **REJECT** via `format_guard.title`.
- `tests/test_format_guard.py`: 5 passed.

## Session 1 continued — Phase 3 / Prompt 12 (Service + CLI)

- `08abceb` feat(service): single entry point for generate, guard and score
- `79691fc` feat(cli): add run command with vertical flag
- Entry: `generator.service.run_vertical` — generate → format_guard → divergence score (deferred until ≥2 verticals on disk).
- CLI: `python -m generator run --vertical legal` (idempotent per `narrative:<vertical>:complete:v<manifest_version>`).
- Clean-state legal e2e: **10 ops**, `guard=passed`, exports under `out/pitch-script-legal-claritydocs.{md,docx}`.
- Immediate re-run: `skipped=True`, ledger `[generate] legal SKIPPED (0 ops)`, total still **10 ops** (no SuperDocs regenerate).

---

## Phase 3 — DONE

**Verified:**

1. Legal speaking script generated end-to-end from clean state via the service/CLI.
2. Format guard passes on the legal markdown + docx exports (structural — not a prose reminder).
3. Idempotent re-run reports **SKIPPED** for the generate step; ops total unchanged.

## Session 1 continued — Phase 4 / Prompt 13 (Fintech + healthcare)

- `ac50c7a` feat(narrative): generate the fintech vertical narrative
- `83e5d41` feat(narrative): generate the healthcare vertical narrative
- `ea89bea` chore(evidence): commit the three narrative exports for side-by-side review
- Exports under `evidence/narratives/` (+ `problem-section-side-by-side.md`).
- Problem-section Jaccard: legal↔fintech **0.167**, legal↔healthcare **0.131**, fintech↔healthcare **0.153** — below 0.55; **not** find-and-replace.
- Cumulative ops after three verticals: **31**.

## Session 1 continued — Phase 4 / Prompt 14 (Edtech + full divergence)

- `4fb2d71` feat(narrative): generate the edtech vertical narrative
- `fd0e4e3` feat(divergence): run the full four-vertical scoring pass
- `acd77a8` chore(evidence): commit the divergence report
- `1119de3` docs: record the divergence results and any section that needed rework
- Four-vertical report: mean vertical **0.115** (&lt; 0.40), mean shared **0.186**, **PASS**, no hot vertical cells (≥ 0.55).
- Rework noted: edtech section 7 heading drifted off `Slide-equivalent 7 — …` — unscored (0.0 cells).

## Session 1 continued — Phase 4 / Prompt 15 (Ledger total)

- `a74b7d9` chore(evidence): commit the full four-vertical ledger
- `a248cbe` docs: reconcile actual ops against the estimated economics in CLAUDE.md
- Actual charged total: **39 ops** (CLAUDE happy-path estimate was ~20). Cause: landed-check split-retries / multi-billable calls per batch. Non-chat steps = 0.

---

## Phase 4 — DONE

**Checkpoint (Prompts 13–15):** three-plus verticals generated; divergence report shows vertical sections diverge and shared may overlap more; ledger reconciled.

| Item | Status |
|---|---|
| Verticals on disk | legal, fintech, healthcare, edtech |
| Exports (reviewable) | `evidence/narratives/pitch-script-*-claritydocs.{md,docx}` |
| Divergence | `evidence/divergence-report.json` — **PASS** (mean vertical 0.115 &lt; 0.40; no cell ≥ 0.55) |
| Human summary | `evidence/divergence-results.md` |
| Ledger snapshot | `evidence/ledger-four-verticals.json` + report txt — **39 ops** |
| Ops reconciliation | `evidence/ops-reconciliation.md` |

**Next phase:** images on `image_eligible` sections (manifest: sections **6** and **8** only); ≥1 image per vertical in the demo. Stub: `src/generator/imagegen.py`. Billing note already filed: `docs/image-generation-billing.md` (image gen = normal chat ops, not a separate SKU).

---

## Session 2 — Phase 5 / Prompt 16 (Image eligibility + generate-where-yes)

- `17dd133` feat(imagegen): decide per-section whether an image is warranted
- `a19a66a` feat(imagegen): generate the image only where the decision is yes
- `217e226` feat(imagegen): charge or flag-as-uncertain the operation cost
- (this) docs: record the eligibility decisions across all four verticals
- Check: `tests/test_imagegen.py` — **10 passed** (no SuperDocs).
- Eligible cells: 8 (4 verticals × sections 6 and 8). **Warranted yes: 4** (fintech 6+8, healthcare 8, edtech 8). **Honest no: 4** (legal 6+8, healthcare 6, edtech 6).
- Billing: confirmed chat op, not a separate SKU (`IMAGE_GENERATION_BILLING_CERTAIN = True`).
- Live SuperDocs insert **not run this session** — no API key in the environment. Metadata sidecars recorded first as required.
- Legal still has 0 warranted images (filler Proof + qualitative ROI). Do not force; rework substance before the demo ≥1-per-vertical bar can include legal.

**Evidence:** `evidence/image-eligibility.md` + `.json`; sidecars `evidence/narratives/pitch-script-*.meta.json`.

---

## Session 2 continued — Phase 5 / Prompt 17 (Image wiring into export)

- `fca3797` feat(narrative): embed generated images at their section with a caption
- (this) test(guard): format guard still passes with an image-bearing export
- Check: `tests/test_narrative_embed.py` + `tests/test_format_guard.py` — **PASS**.
- Export post-process places the figure after the talking point of the named slide-equivalent, captioned `Presenter visual (not a slide): …`.
- Demo (fintech §6): `evidence/image-demo/pitch-script-fintech-claritydocs.md` + `presenter-visuals/fintech-section-6.png`. Format guard **PASS** with the image present.

---

## Session 2 continued — Phase 6 / Prompt 18 (Compliance pass)

- One §5 fail: healthcare export claimed HIPAA was met "by design" and treated PHI redaction as automatic (`PHI redacted, of course`).
- Fill instructions now forbid certification and guaranteed-redaction overclaims; healthcare evidence script rewritten; `tests/test_compliance.py` scans exports.
- Other §5 checks **PASS** (ON SuperDocs, fictional clients, no roadmap dependency).

---

## Session 2 continued — Phase 7 / Prompt 19 (FastAPI routes)

- `4b328e0` feat(api): expose verticals, generate, and narrative export
- `dba1aeb` feat(api): expose divergence report and ledger
- (this) feat(api): background run with polling for generation
- Check: `tests/test_api.py` — **PASS** (mocked generate; no SuperDocs).
- `POST /generate` returns **202** `{run_id}` immediately; poll `GET /runs/{run_id}`.
- Serve: `uvicorn generator.api.app:app --reload` from this folder (after install).

---

## Session 2 continued — Phase 7 / Prompt 20 (Divergence screen)

- `e794e00` chore(ui): scaffold React and Vite
- `c1a01f7` feat(ui): divergence screen with per-weight-class summary
- (this) feat(ui): per-section-per-pair grid and pass/fail state
- Hero: `ui/` — `npm run dev`. Vertical mean vs shared mean, pair×section grid, Pass/Fail.
- No chart library. Report snapshot: `ui/src/data/divergence-report.json`.

---

## Session 2 continued — Phase 7 / Prompt 21 (Remaining screens)

- `f1ecbdb` feat(ui): verticals screen
- `49313c0` feat(ui): generate screen with live ledger
- `3039a5f` feat(ui): narratives screen with speaker notes and images
- (this) docs: record Phase 7 UI coverage
- Check: `npm run build` in `ui/` — **PASS**.

---

## Phase 7 — DONE

**UI coverage** (`ui/` · `npm run dev`; FastAPI on `:8000` for live generate/ledger/docx):

| Screen | Route | What it shows |
|---|---|---|
| Divergence | `#/divergence` | Pass/Fail, vertical vs shared means, pair×section grid |
| Verticals | `#/verticals` | Knowledge-file summary: buyer, trigger, pain, objection, proof, terminology |
| Generate | `#/generate` | Queue `POST /generate` (202 + poll); live `GET /ledger` (snapshot if API down) |
| Narratives | `#/narratives` | Four exports; speaker notes; presenter visual on fintech §6; eligibility notes |

Same paper/ink editorial language as Divergence. No chart library. Generate proxies `/api` → `127.0.0.1:8000`.

**API (Prompt 19):** `GET /verticals` · `POST /generate` → 202 · `GET /runs/{id}` · `GET /narratives/{vertical}` · `GET /divergence` · `GET /ledger`.

---

## Handoff for the next chat session

**Branch:** `kathans22/pitch-deck-narrative` (pushed; work only under `use-cases/kathans22/pitch-deck-narrative/`).

**Do first every session:** read local `CLAUDE.md` (working agreement — **do not commit it**). Follow its fixed decisions, bug-evidence rule, and commit protocol. Update this `PROGRESS.md` at session end.

**Do not use** `build2-sequential-prompts.md` numbering as source of truth — it does not match the live pasted-prompt sequence. Follow the prompt the user pastes + `CLAUDE.md` + this file.

**CLI (already works):**
```text
python -m generator run --vertical <legal|fintech|healthcare|edtech>
python -m generator score --from evidence/narratives
```
Idempotent: re-run of a finished vertical for the current manifest version → ledger `SKIPPED` (no regenerate).

**API key:** not in this repo. Load from env or local `.env` (gitignored). Dev habit has been Build 1’s `.env` under `policy-pack-localizer` — never commit keys/emails.

**Known defects to carry forward (do not rediscover):**
1. **Signed SuperDocs image URLs expire (~24h)** — exports now mirror figures under `evidence/narratives/presenter-visuals/` (and `ui/public/presenter-visuals/`). Prefer those local files.
2. **BUG-002** — healthcare image chat also appended generic `## Section N` blocks and `placeholder.com` figures; stripped from the evidence markdown. See `evidence/bugs/BUG-002-image-insert-extra-sections.md`.
3. **Ops budgeting** — plan **~8–12 ops/vertical** with retries on, not CLAUDE’s happy-path 5. Four verticals originally cost **39**. Live image insert this pass: **8 chat ops** (two warranted figures × four verticals).
4. **Secrets** — `.env` and `.cursor/mcp.json` hold the live key and are gitignored. Copy `.env.example` / `.cursor/mcp.json.example`. Never commit a Bearer token. `OPS_BUDGET_CAP=20` in `.env` will block a run against the 39-op ledger; raise it in the shell for image/generate work.

**Evidence already committed (prefer these over gitignored `out/` / `state/`):**
- `evidence/narratives/` — four speaking scripts + `.meta.json` image decisions
- `evidence/image-eligibility.md` / `image-eligibility.json`
- `evidence/image-demo/` — fintech speaking script with §6 presenter visual in place
- `evidence/divergence-report.json` / `divergence-results.md`
- `evidence/ledger-four-verticals.json` / `ops-reconciliation.md`
- `evidence/bugs/` — SuperDocs surprises

**Commit hygiene reminder:** `git add` specific paths only; never stage `.env`, keys, emails, `out/`, or `state/`; `evidence/` is fine; push `kathans22/pitch-deck-narrative`.

---

## Phase 8 / ship — Prompts 22–26 (final)

**What shipped**

- Four vertical speaking scripts (legal, fintech, healthcare, edtech) via SuperDocs MCP; format guard (“Speaking script — not a slide deck”); divergence **PASS** (rescored vertical mean ~0.192, shared ~0.219).
- Image eligibility + live insert where warranted; local mirrors under `evidence/narratives/presenter-visuals/` (and UI public copies).
- FastAPI + React UI (divergence / verticals / generate / narratives); `docker compose up --build` one-command run with ERROR / Cause / Fix startup messages.
- README (what / run / SuperDocs features / real divergence + ledger / bugs / limitations); BUG-001 and BUG-002 rollup; secret hygiene (placeholders only; absolute path stripped from live test).
- CONTRIBUTING alignment: folder `use-cases/kathans22/pitch-deck-narrative/` only (`git diff --stat main...HEAD` has nothing outside); MIT `LICENSE` + README license note; demo = local compose URLs.

**Ops (this build):** narrative ledger **39** chat ops across four verticals; live image insert **+8** chat ops. Export / score / UI snapshots = **0** SuperDocs ops.

**What didn’t**

- No hosted public demo URL or polished walkthrough screenshot PNGs under `docs/demo/` (placeholders only; demo is local compose).
- UI vertical list still hardcoded to the four packs (not dynamic from API alone).
- Image signed URLs still expire; healthcare still needed a post-export strip for BUG-002 extras.
- Happy-path “5 ops/vertical” from CLAUDE was not reality once landed-check retries ran.

**What’s next with more time**

- Host a short demo (or fill `docs/demo/*.png`) and wire UI verticals from `GET /verticals`.
- Harden image insert so BUG-002 cannot append junk sections; refresh or drop signed URLs in favor of mirrored assets only.
- Optional: fifth vertical = YAML only; tighten ops budgeting / retry policy so ledger matches plan without manual `OPS_BUDGET_CAP` bumps.

**PR description draft** (no email — paste into the GitHub PR):

- **Name:** Kathan Shah
- **Title:** ClarityDocs vertical pitch-script narrative generator
- **Body:** Generates vertical-specific ClarityDocs speaking scripts (not slide decks) over SuperDocs MCP, with measured divergence across legal/fintech/healthcare/edtech, FastAPI + UI, and docker-compose one-command run.
