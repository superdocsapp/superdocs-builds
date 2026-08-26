# Policy Pack Localizer — working agreement

A tool for an NGO safeguarding lead. One master policy → per-country packs, each in the
office's working language, with the non-negotiable core intact and local annexes swapped.
Built ON SuperDocs, driving it over MCP. Never a reimplementation of it.

## Fixed decisions — do not revisit these

1. **Core identity is per-language.** A translated core cannot be byte-identical to English.
   Each language's core is derived exactly once and hash-locked. Every pack in that language
   carries that identical locked text. France and Senegal share one core hash — that is the
   demo's central proof and the reason both are in the country set.
2. **The English core is authoritative.** Every pack states that translations are provided
   for working use. We never imply legal equivalence for a machine translation.
3. **Protection is by verification, not by instruction.** Edit instructions name annex
   sections only; core sections are never named in any instruction. But the guarantee is
   enforced by hashing the core out of every export and comparing. Instruction = intent.
   Hash = enforcement.
4. **No sentinel markers in the document text.** The core/annex split lives in
   `config/manifest.yaml`. The shipped document stays clean.
5. **Adding a country is a YAML file.** Adding a language costs one translation operation
   and zero code. If a country needs a code change, the design is wrong.
6. **The acknowledgement form is deterministic.** Known fields into a known template.
   Zero operations. SuperDocs renders and exports it; export is free.
7. **All organisations, offices, people and contacts are invented** (Meridian Relief Trust).
   Statutes referenced are real law — fabricated legislation would make the annexes
   meaningless as a demonstration of country-specificity.

## The document shape

Sections 1–5 CORE · 6–9 ANNEX (6 reporting, 7 legal, 8 escalation, 9 acknowledgement).

## Operation economics — the batching rule

- Lock core: **0 ops** (arithmetic)
- Translate core per language: **1 op**, cached by `(core_version, language)`
- Generate a pack: **2 ops** — sections 6–9 replaced via `annex_batch_size`-sized batched
  chat calls (config, default 2 sections/call — see `config/manifest.yaml` and
  `evidence/superdocs-batch-limit-report.md`). Live testing proved SuperDocs does not
  reliably apply all four annex sections in one call — a batch can report full success while
  changing nothing. Each batch is verified against the document, not trusted from the
  response; a batch that didn't land is split and retried. Two batches of two is the floor
  proven safe enough to build on; do not hardcode a larger number because it happened to work
  in a trial — see the evidence file for why.
- Acknowledgement form: **0 ops**
- Upload, export, download: **0 ops**
- Change notice per country: **1 op** on a clean landing — a single-document call, unlike a
  pack's multi-section batch. Live testing (Prompts 20–21, `evidence/run2-ledger.md`) showed
  the same "billed but nothing changed" failure SuperDocs exhibits on annex batches also
  occurs on this single call: a confused non-edit response, `changes: null`, still billed.
  `send_change_notice` never trusts the response — it verifies the export and retries once
  (bounded) — so a notice needing a retry honestly costs **2 ops**, not 1. Two of five did,
  live, in the real Run 2.
- Re-translate a changed section: **1 op per affected language**, not per country

Full rollout, 5 countries / 3 languages: **12 ops** (2 translations + 5 packs × 2). Core
amendment reaching all 5: **7 ops** idealised (2 re-translations + 5 notices) — the real,
fully-itemised Run 2 cost **9 ops**, because 2 of the 5 notice calls needed the retry above
(`evidence/run2-ledger.md`). An update still costs like an update, not like a reissue: zero
packs were regenerated either way, and the 7-vs-7 idealised equivalence against Run 1 is the
comparison that matters — the +2 is the same live-flakiness tax paid throughout this build,
not a batching cost creeping back in.

## Non-negotiable engineering rules

- **One normalisation function**, shared by lock-time and verify-time. Nothing else may
  normalise text. Its rules are documented in a docstring.
- **Idempotency wherever an operation costs money.** A pack or translation already produced
  for the same inputs is not re-bought.
- **Never add an aggressive timeout.** SuperDocs calls legitimately take 30 seconds to
  several minutes with no visible progress. That is processing, not a crash.
- **Proposed-change content is a JSON-encoded string and needs a second parse.** The final
  result is already an object. Exactly one helper does this, and everything goes through it.
- **A hash mismatch quarantines the pack.** It is not shipped and the run does not report
  success. A success message only ever means the output is genuinely in the state it claims.
- **Secrets are placeholders only:** `SUPERDOCS_API_KEY=your-key-here`. No key in a file,
  a commit, a log, or a shell history. No email address anywhere in this repository.

## COMMIT PROTOCOL — applies to every prompt, always

Each prompt gives me a `Commits:` list. That list is the plan for the session.

**Work in the order the list gives.** Complete one commit's worth of work, stop, and run
this cycle before starting the next:

1. **Show me the diff summary** — files created, files changed, lines added and removed.
   Not the full file contents unless I ask.
2. **Run the check** for that unit — the import works, the test passes, the command runs.
   State the result. If it fails, fix it before committing. Never commit broken work.
3. **Pre-commit gate**, every time, no exceptions:
   - `git status` shows no path outside `use-cases/kathans22/policy-pack-localizer/`
   - No `.env`, no real API key, no email address, no absolute path from my machine
   - `out/` and `state/` are not staged; evidence goes in `evidence/`
4. **Commit and push** with the exact message from the list:
   `git add <specific paths>` — never `git add .`
   `git commit -m "<message from the list>"`
   `git push origin kathans22/policy-pack-localizer`
5. **Say which commit number you just pushed**, then move to the next.

**One unit of work = one commit.** Never batch a prompt's commits into one. Never split a
commit into fragments to raise the count — the list is the granularity.

If a unit turns out to be wrong after committing, fix it forward with a `fix:` commit that
names what was wrong. Do not amend or rebase pushed history.

Message style is conventional commits: `feat(scope):`, `test(scope):`, `fix(scope):`,
`docs:`, `chore:`. Imperative mood, lowercase after the colon, no trailing period.

## How to work with me

- Do only what the current prompt asks. No extra features, no speculative abstraction,
  no tests I did not ask for.
- Read only the files a prompt names. Do not scan the tree.
- If something in the plan is wrong, stop and say so before writing code.
- If you cannot support a claim, say so. A flagged gap is fine; an invented fact is not.
- End substantial sessions by updating `PROGRESS.md`.
