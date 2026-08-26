# Progress

## Phase 0 — Ground (Session 1)
Scaffolded the package (`src/localizer/*`, `config/`, `out/`, `state/`, `evidence/`, `tests/`),
`.gitignore`/`.env.example`, and `pyproject.toml` (Python 3.12, fastapi/uvicorn/pyyaml/httpx/mcp).
`python -c "import localizer"` passes.

## Phase 1 — The spine, no model calls (Session 2)
Built and proved the integrity mechanism on hand-made files, with no SuperDocs calls involved:

- `config/policy-master.md` — the 9-section Meridian Relief Trust policy (5 core, 4 annex
  placeholders) — and `config/manifest.yaml` declaring the core/annex split and annex slots.
- Five country packs (`config/countries/{IN,KE,FR,SN,BR}.yaml`), each with genuinely distinct
  reporting channels, legal instruments, and escalation tiers; FR/SN in French, BR in Portuguese.
- `config.py` — loads and validates the manifest and every country file, failing loudly with
  the specific missing field.
- `sections.py` — parses `policy-master.md` into numbered sections by heading boundary, and
  asserts the parsed headings match the manifest exactly.
- `corelock.py` — the mechanism the whole build rests on: `normalise()`, `lock()`,
  `save_lock`/`load_lock`, `verify()`.

**Proven, by `tests/test_corelock.py` (8 tests, all passing):**
- Identical core content in two different files produces one identical `core_hash`.
- A one-word change to a core section changes exactly that section's hash and the `core_hash`;
  the other core sections' hashes are untouched.
- Changing an annex section changes neither a core section hash nor the `core_hash`.
- Round-trip resilience, one test per mutation: quote style, trailing whitespace, blank-line
  runs, line endings, list marker style — each proven to leave the `core_hash` unchanged.

**The normalisation contract, in one sentence:** `normalise()` canonicalises Unicode form,
line endings, quote style, dash-glyph family, space-character family, list-marker glyphs,
blank-line runs, and incidental whitespace — while leaving case and all actual wording,
numbers, and word order untouched — so a cosmetic round trip through an editor never
registers as a change, but any real edit still does.

**Deviation from plan:** the round-trip tests (commit 3 of Prompt 6) use small hand-authored
inline fixtures per mutation rather than mutating `config/policy-master.md` directly. The
master's core sections are single unbroken paragraphs with no internal line breaks, so
mutations like "blank-line runs" or "line endings" had no internal structure to act on without
first synthesising one — at which point the fixture is hand-authored either way. Commits 1–2
of Prompt 6 do use real file fixtures (`tests/fixtures/policy_fixture_{a,b}.md`) parsed through
`sections.load_sections`, per the brief.

## Phase 2 — MCP client and the four calls (Session 3, Prompts 7–10)

Built `mcp_client.py` (connect + upload/chat/approve/export + `parse_proposed_changes`),
`ledger.py` (cost record, persistence, report, idempotency, `--limit`/ceiling), and
`scripts/smoke.py`, all driven against the **real** SuperDocs MCP server — not mocks.

### The four MCP tools — real signatures, verified live

Endpoint `https://api.superdocs.app/mcp/`, streamable HTTP, `Authorization: Bearer sk_...`.

| Tool | Required | Key optional |
|---|---|---|
| `upload_document_base64` | `filename` (≤512), `file_base64` (≤50M chars) | `session_id` (auto-gen if omitted), `return_html` |
| `chat` (sync) | `message` (≤100k), `session_id` (pattern `^[a-zA-Z0-9_\-\.]+$`) | `approval_mode` (`approve_all` default / `ask_every_time`), `response_mode` (`full`/`compact`) |
| `approve_change` | `session_id`, `job_id` | `change_id`, `approved`, `feedback`, `changes` (batch) |
| `export_document` | one of `session_id`/`html`/`upload_id` | `format` (docx default/pdf/html/markdown/txt), `options` |

### Raw proposed-change shape (see `tests/fixtures/proposed-change-raw.json` for the full
recording, and Prompt 10's live run for the sync-chat variant)

Two shapes carry the same data:
- **Already-an-object**: `metadata.pending_changes` (chat_async/get_job) or
  `document_changes.pending_changes` (sync chat) — a list of
  `{change_id, operation, chunk_id, document_id, old_html, new_html, ai_explanation}` dicts.
- **Double-encoded**: `metadata.intermediate_responses[]` entries of
  `type: "proposed_change_batch"` carry `content` as a **JSON-encoded string**
  (`{"type", "batch_id", "batch_total", "changes": [...]}`), only present on the
  chat_async/job path.

`parse_proposed_changes()` (Prompt 8) hides this distinction; both were proven against the
real recorded fixture.

### Observed latency

Exactly one precise timing was captured with real timestamps: the chat_async batch edit in
Prompt 8 went from job `created_at` to `awaiting_approval` in **~7.15s**
(`08:31:51.997` → `08:31:59.145`). The synchronous `chat`/`upload`/`export` calls made live in
Prompt 10 were exercised through this session's SuperDocs MCP tools directly (see below for
why), which don't expose call timing in their response bodies — so no comparable stopwatch
figure exists for those calls in this record. `smoke.py` itself instruments every call with
`time.monotonic()` and reports wall time per ledger row; running it end-to-end with a real
`SUPERDOCS_API_KEY` would produce that data directly. Qualitatively, every call observed so far
completed in single-digit seconds — nowhere near `mcp_client.py`'s 900s ceiling.

### Where the docs and the real API disagreed

1. **`approve_change` only works against a `chat_async` job — not a synchronous `chat`
   preview.** Calling `chat` with `approval_mode='ask_every_time'` returns
   `document_changes.pending_changes` with `requires_approval: true`, exactly as documented —
   but that response carries no `job_id`, and `approve_change` requires one. Calling it with the
   `session_id` in place of `job_id` returns `HTTP 404 Not Found — {'detail': 'Job not found'}`.
   The docs describe `approve_change` as the HITL partner for both `chat` and `chat_async`
   without flagging that only the async job path actually has something to approve against.
   `scripts/smoke.py` demonstrates this directly: it calls `approve()`, the call fails exactly
   as described, and the script falls back to a second `chat` call (default `approve_all`) to
   actually apply the edit.
2. **A preview-only chat call is free; only an applied edit is billed.** The `ask_every_time`
   preview response came back with `"usage": null`. The follow-up call that actually applied the
   change came back with `"usage": {"was_billable": true, "ops_charged": 1, ...}`. Nothing in the
   docs states that proposing a change costs nothing while applying it costs one operation —
   this matters for `ledger.py`, whose current model (Prompt 9) charges 1 operation per `chat`
   call unconditionally. `smoke.py` charges from the response's real `usage` field instead of
   assuming a constant; `ledger.py`'s charging model should eventually do the same, but that
   change is out of this prompt's scope.
3. **The installed `mcp` Python SDK (v2.0.0) doesn't match the API the docs' example patterns
   assume** (found in Prompt 7): the real function is `streamable_http_client`, not
   `streamablehttp_client`; auth is set by constructing an `httpx2.AsyncClient` and passing it as
   `http_client=`, not a `headers=` kwarg on the transport call; and the library is `httpx2`
   (a dependency of `mcp` itself), not `httpx`. `httpx2.AsyncClient` also defaults to a 5-second
   timeout, which had to be overridden explicitly to honor CLAUDE.md's "no aggressive timeout"
   rule.
4. **The sync-chat and chat_async proposed-change shapes aren't quite identical.** The sync
   `chat` preview's `pending_changes` entries have no `insert_after_chunk_id` field and no
   outer `batch_id`/`batch_total` wrapper; the chat_async/job path's double-encoded batch does.
   `parse_proposed_changes()` treats both as valid without requiring those fields, since they're
   documented nowhere as guaranteed.

### How Prompt 10 was actually run

`scripts/smoke.py` is correct, real production code, but this sandbox's Bash environment has no
`SUPERDOCS_API_KEY` or network path wired to it (only `mcp__superdocs__*` tool calls in this
session are authenticated, at the harness level). So the exact operation sequence `smoke.py`
performs — upload `policy-master.md`, preview a section-6-only edit, attempt approve (fails as
documented), fall back to an applying chat call, export markdown — was run for real via those
live tools first, and `smoke.py`'s internal logic (parsing, ledger charging, the approve-fallback
path, section extraction) was then verified offline by replaying those exact real captured
responses through `smoke.run()` with only the network boundary substituted. The real export
confirmed sections 1–5 and 7–9 were untouched; only section 6 changed, to:

> India Office: Internal contact is the Country Safeguarding Focal Point, Mumbai, reachable at
> safeguarding.in@meridian-relief.example or +91 22 0000 0000. External channels: Childline
> India (1098, toll-free 24-hour child helpline) and the Police Control Room (112).

### fix(ledger): charge chat calls from real usage, not a flat 1 per call

What was wrong: `ledger.py` (Prompt 9) charged every `chat` call 1 operation
unconditionally. Finding 2 above proved that's incorrect — a preview-only call is free.
Left as-is, `ledger.py` would overcount any future preview call, which breaks the ledger's
entire purpose: it is supposed to answer "what did this actually cost," not "how many calls
did we make." `smoke.py` already worked around this locally with its own `_ops_charged()`
helper, but the fix belongs in `ledger.py` itself, where every other caller can use it.

Fix: added `ops_from_response(response) -> int` to `ledger.py` — reads `usage.was_billable`
and `usage.ops_charged` from a real SuperDocs response instead of assuming a constant.
`smoke.py`'s local copy was removed in favour of importing this. Re-verified against the
same real captured payloads from the Prompt 10 run: ledger total is still correctly 1 op
(0 for the preview, 1 for the apply). Full test suite (10 tests) still passes.

Not yet done, flagged for whichever prompt next builds the pack-generation path
(`packs.py`, Phase 3+): that code should call `ledger.record(..., chat_calls=
ledger.ops_from_response(chat_response))` rather than a hardcoded `chat_calls=1`, even
though CLAUDE.md's stated economics ("1 op per pack") will still hold in practice — a
real pack-generation call always applies a change, so it will always be billed — the
point is not to bake the *assumption* back in a second time. (Done: `packs.py` does exactly
this now — see Phase 3 below.)

## Phase 3 — One country, end to end (Session 4, Prompts 11–12)

**Prompt 11** implemented `packs.py`: `generate_pack(country_code)` — upload, batched annex
edit, export to markdown and docx, idempotent per-`(country_code, core_version)` charging via
`ledger`. The instruction builder (`build_instruction`) names annex sections only;
`assert_no_core_sections_named` is a hard stop enforced before any call is sent, and
`corelock.verify` after export is the enforcement half of the same guarantee.

**Prompt 12** asked for the India round trip end to end, core hash verified against the lock.
Live testing surfaced a real, blocking bug in SuperDocs itself before verification was even
reached — the edit wasn't landing. Full detail, repro, and billing findings:
`evidence/superdocs-batch-limit-report.md`. Summary:

- A batched `chat` call replacing all 4 annex sections in one request **reports success and
  changes nothing**, reproduced with two structurally different instruction phrasings.
- Pinned precisely, live: 1, 2, and 3 sections in one call can all succeed; 4 fails
  consistently. But 2-section batches were *also* observed to silently drop one of the two
  targeted sections on other trials — so no batch size above 1 is safe to assume reliable,
  including sizes proven to work in an earlier trial.
- A session that has just experienced a partial/failed batch can misattribute a later,
  differently-scoped single-section retry to the wrong section entirely.
- Billing: a **novel** failing batch is billed once (`ops_charged: 1` for zero changes); an
  **identical retry** of that same failing instruction is not billed; a bare transient error
  (`"I encountered an issue. Please try again."`) is billed.

**The fix** (per-user direction — do not hardcode the boundary; add real detection and
recovery instead of a threshold):

- `config/manifest.yaml` gained a required `annex_batch_size` field (currently `2`) — a live,
  undocumented API characteristic belongs in config, adjustable as it's re-verified, never a
  Python constant.
- `packs.py`'s `generate_pack` now sends the annex edit in `annex_batch_size` batches via
  `_localise_annex` → `_apply_annex_batch`. After every batch, it re-exports and checks each
  targeted section's actual body against the master's original text (`_sections_landed`) —
  never trusting the response text. Any section that didn't land has its batch split
  (bisected) and retried, bounded by `_MAX_RETRY_DEPTH`. A section still unlanded after
  isolation to a batch of one falls through to `verify_pack`'s existing placeholder check,
  which quarantines the pack rather than shipping it silently incomplete.
- Removed the now-obsolete `ask_every_time` preview + `approve_change` fallback path and its
  regex-based partial-apply detection (`_PARTIAL_APPLY_RE`) — `approve_change` never worked
  against a synchronous `chat()` call regardless (Prompt 10 finding), and the regex matched a
  response shape ("Updated X of Y sections") different from every failure shape actually
  observed live.
- `tests/test_packs.py` rewritten around a fake client that tracks real document mutation
  (`_MutatingFakeClient`), including a test that reproduces the exact live bug (a batch that
  reports success and changes nothing) and proves detection + split-retry recovers from it.
- `CLAUDE.md`'s economics corrected: a pack costs **2 ops**, not 1. Full rollout **12** (2
  translations + 5 packs × 2); core amendment reaching all 5 stays **7** (2 re-translations +
  5 single-document notices — a notice isn't a batched multi-section call, so its cost is
  unaffected).

**The real India round trip, live** (session `pack-in-real`, after the fix): uploaded the real
`config/policy-master.md`, sent the batched annex edit as `annex_batch_size=2` batches (with
several of the partial-failure symptoms above occurring and being manually worked through
live, exactly as the automated retry path is designed to handle), exported markdown, ran the
real `corelock.lock()`/`packs.verify_pack()`:

```
locked core_hash: aa3a7460e6602b04e59acbe8ef73be464c3951624b50903a61b548ce64e186e8
passed: True
core passed: True
core_hash_matches: True
diverged_sections: []
unlocalised_annex_sections: []
```

India's pack — core sections 1–5 byte-identical to the lock, all four annex sections
genuinely localised (India-specific email/phone/helplines, POCSO/POSH/JJ Act citations,
Mumbai escalation tiers, NCPCR) — is saved at `out/IN/policy-pack.md` and `out/IN/policy-pack.docx`
(gitignored; not committed, per CLAUDE.md).

**Deviation from plan:** Prompt 12's checkpoint description assumed a single batched call
would work and only verification remained to prove. It didn't — the batching assumption
itself was wrong, discovered only by running it live rather than trusting the design. Fixed
forward per CLAUDE.md's own commit protocol, with a full bug report filed
(`evidence/superdocs-batch-limit-report.md`) rather than silently working around it.

## Phase 3 continued — service layer and CLI (Prompt 13)

`service.py` is now the single entry point both the CLI and any future FastAPI route call —
neither reimplements lock/generate/verify:

- `lock_core()` — locks `policy-master.md`'s core sections for one language. 0 ops.
- `generate(country_code, ...)` — thin wrapper over `packs.generate_pack`.
- `verify(country_code, ...)` — re-verifies an already-generated pack on disk against the lock,
  without regenerating it.
- `run(country_codes, *, limit=None, ...)` — loads the persisted ledger, locks the core, generates
  a pack per country (respecting `--limit`), saves the ledger. What the CLI's `run` command calls.

`python -m localizer run --countries IN [--limit N]` (`src/localizer/__main__.py`) is a thin
argparse wrapper over `service.run`; it prints per-country OK/SKIPPED and the ledger report.

**Run it clean, then run it again — real result**, real `out/` and `state/` cleared first
(including a leftover `out/_quarantine/IN/` from an earlier offline test that had wrongly
landed in the real project directory — removed):

First run (via live SuperDocs calls, since this sandbox has no `SUPERDOCS_API_KEY` wired to
its own process — see Prompt 10/12 for why; the CLI itself needs no such workaround with a
real key) reproduced the same partial-batch behaviour documented in
`evidence/superdocs-batch-limit-report.md`: the `[6, 7]` batch landed only section 7; a
`[6]`-alone retry failed once (free) then succeeded; the `[8, 9]` batch landed cleanly. Real
cost for this run: **3 ops**, not the idealised 2 — CLAUDE.md's "2 ops" is what a clean batch
run costs; a run that needs one retry costs more, and the ledger records that honestly rather
than reporting an assumed constant. `verify_pack` passed: core hash matched the lock exactly,
zero unlocalised annex sections (see note below on why section 9's retained placeholder
sentence didn't false-positive this check).

Second run, the actual command, no code path touching the network at all:
```
$ python -m localizer run --countries IN
[IN] SKIPPED

...
[pack]      IN                                           0 ops
[pack]      IN                                 SKIPPED (0 ops)
                                                       -------
total                                                    3 ops
```
Total stayed at 3 — the second run added exactly one new SKIPPED ledger line and zero
operations. Also confirmed `--countries IN,KE --limit 1` processes only `IN`; `KE` is never
attempted, not even skipped-and-logged — `apply_limit` slices the country list before any
country is touched.

**Observation, not a bug:** section 9's original body has its two sentences joined by a
single `\n` in `policy-master.md`, but SuperDocs' HTML→markdown export renders the `<br/>`
that single `\n` becomes on upload as a full paragraph break (`\n\n`) on export — even when
new content is appended after the original placeholder sentence rather than replacing it
(observed live), the exact placeholder substring no longer matches verbatim, so
`_sections_landed`/`verify_pack` correctly does not flag it as still-unlocalised. This is
fortunate rather than by design; a future SuperDocs export change that preserved single `\n`
literally could reintroduce a false "not landed" retry loop or, worse, a false-pass on a
section that only had content appended around an intact placeholder. Worth hardening later
(e.g. checking the placeholder no longer appears as the section's *entire* content, not just
checking it as a substring) — not done now, out of this prompt's scope.

## Phase 4 — Translation and multi-language (Session 5, Prompts 14–16)

**Prompt 14** implemented `translate.derive_core(language)`: derives, hashes, and locks a
language's translated core exactly once, cached by `(core_version, language)`. The
translation instruction is the one legitimate place in the codebase that names core
sections — structurally isolated by never importing `packs.py`, so `packs.assert_no_core_sections_named`
can never see it. The lock file gained a `sections` key holding the verbatim translated
text (heading + body per section), alongside the existing hashes, so a later pack can insert
the translated core without ever re-translating it.

**Prompt 15** extended `packs.py` so a non-English country's pack is assembled from that
language's locked core (verbatim, via `_assemble_upload_document`) plus its own annexes, with
`_assert_core_verbatim` proving the match locally before any SuperDocs call is made. FR and
SN — two French-speaking countries with entirely different annexes — were built and their
core hashes compared: identical, as required.

**Prompt 16** ran all five countries live (IN, KE, FR, SN, BR) to a genuinely clean, verified
state and produced `evidence/integrity-report.json`.

**What "clean" actually took.** The first pass through every non-trivial annex batch/fix-up
call surfaced defects beyond the partial-batch behaviour already documented in
`evidence/superdocs-batch-limit-report.md`:

- A batch reporting full success while leaving part of a multi-sentence placeholder attached
  before or after the new localised text (FR §6/§8/§9, SN §6/§7/§8, IN §6/§8/§9 all showed
  this — the master's placeholder sentence surviving verbatim alongside real content).
- A batch editing the wrong chunk entirely — writing new content into the `<h2>` **heading**
  chunk instead of the `<p>` **body** chunk, corrupting the heading while leaving the body's
  placeholder untouched (BR §6/§7, observed live).
- A "concurrent edit notice" (`concurrent_merges`) appearing on at least one retry, indicating
  cross-request interference on the same document; the affected edit (KE §7) still needed a
  second pass afterward because the merge silently reverted it despite the response reporting
  success.
- Natural-language `chat()` instructions repeatedly failing to touch a corrupted **heading**
  specifically (`"nothing actually changed"`, 0 ops charged, three separate attempts on BR),
  even when the exact chunk id was named. What reliably worked instead: fetching the current
  full document HTML and re-submitting it via `chat(document_html=...)` as a verbatim
  replacement (the tool's documented "load, don't retype" path) rather than asking the AI to
  edit in place — 0 ops charged each time, since it is a document load, not an AI edit.

All five packs were brought to a verified-clean state this way and re-exported. Locally
re-running `packs.verify_pack` against every exported markdown (not the chat response)
confirms:

```
IN en passed=True unlocalised=[] core_hash_match=True
KE en passed=True unlocalised=[] core_hash_match=True
FR fr passed=True unlocalised=[] core_hash_match=True
SN fr passed=True unlocalised=[] core_hash_match=True
BR pt passed=True unlocalised=[] core_hash_match=True
```

**The three real core hashes** (`evidence/integrity-report.json`, `core_identity`):

- en (IN, KE): `aa3a7460e6602b04e59acbe8ef73be464c3951624b50903a61b548ce64e186e8`
- fr (FR, SN): `a240052d992b3f53af2332edd0ffe62172b87e6a963c3c8dd4dfef4d47dafa58`
- pt (BR): `4d339a737d5ea69c3bfd38ee983f779243c219ba869e1e9df443bb98ef7cf9b8`

FR and SN's identical hash — two French-speaking countries, two entirely different annexes,
one identical locked core — is the demo's central proof, now verified from five real,
independently-generated exports, not asserted.

**Annex divergence**, counted (not claimed) across the same normalisation `corelock` uses:
`reporting`: 5 distinct, `legal`: 5 distinct, `escalation`: 5 distinct — every one of the five
countries' three non-acknowledgement annex slots is genuinely unique content.

**Translation quality vs. annex-editing completeness — kept separate, deliberately.** The
translated CORE text itself (fr and pt, from `translate.derive_core`) read as accurate,
idiomatic legal French and Portuguese on inspection — no quality concerns there. The defects
above were entirely in ANNEX EDITING completeness and precision (partial replacements,
wrong-chunk edits, a reverted concurrent merge), not in translation. KE (English throughout,
no translation involved at all) needed the same class of remediation as FR/SN/BR, which
confirms the defects are a `chat()`-edit reliability issue, not a translation-quality one.

**Operations.** Full itemisation and the honest total (well above both the user's stated
7-op expectation and CLAUDE.md's own idealised 12-op full-rollout figure — annotated with
why) is in `evidence/ledger-summary.md`, not duplicated here. In short: the idealised model
prices a pack at 2 ops (one per annex batch); the real run cost more per pack because
recovering from the defects above took extra `chat()` turns per affected country before
`verify_pack` could honestly report every section clean.

## Phase 5 — Acknowledgement forms (Session 6, Prompt 17)

Implemented `ack.py`: `render_form(country, manifest)` builds the acknowledgement
markdown deterministically — office name, country, pack version, the protected core hash
(read from the persisted `state/core-lock-v1-{lang}.json`, never recomputed), safeguarding
lead, and blank recipient/date/signature fields, with field labels and the confirmation
statement in the office's working language (en/fr/pt) from a small static dictionary.
`generate_acknowledgement(country_code)` uploads and exports it via SuperDocs.

**Decision: no chat call, ever, for this document.** Filling known fields from a known
country YAML into a known template has no ambiguity for a model to resolve — the fields
either exist in the YAML and the lock, or they don't. Spending an operation on it would be,
per CLAUDE.md, spending money to do arithmetic badly. SuperDocs is used only for the parts
it actually adds value on: upload (turns the markdown into a document SuperDocs can render)
and export (produces the styled `.docx` the office actually signs) — both free.

**Live proof, all five countries** (`evidence/ack-generation-report.md`): uploaded and
exported IN/KE/FR/SN/BR's forms via the real SuperDocs MCP tools. Every `upload`/`export`
response carried no `usage` field at all — the same "absent = free" signal
`ledger.ops_from_response` already treats as zero — so the ledger total across all ten
calls is **0 operations**. Each core hash embedded matches that country's language lock
exactly; Senegal's and France's forms carry the identical `fr` core hash, the same proof
the packs themselves carry.

**Return address, one deviation from the brief's field list.** No country YAML carries a
distinct postal address — `office` and `country` are all that exist. Rather than adding a
sixth field to five YAML files for a string that would just repeat those two values,
`return_address` is derived as `f"{office}, {country}"`. If a real postal address is ever
needed, it is a one-field addition to each country YAML, consistent with "adding a country
(or a field) is a data change."

## Phase 6 — Amendment (Session 7, Prompts 18–21)

The hardest requirement, and the one that most distinguishes the build: a core amendment
must produce a per-country change notice, not a full reissue, and cost like an update.

**Prompt 18 — section-level diff.** Amended `config/policy-master.md` section 4 to add an
explicit 24-hour reporting deadline; archived the pre-amendment text at
`config/policy-master-v1.md` (both versions kept, so a notice can quote either); bumped
`manifest.yaml`'s `core_version` to 2. `amend.diff_core_versions(manifest, language,
from_version, to_version)` compares only the persisted locked hashes (zero SuperDocs
calls) and `format_diff_report()` produces the required `"Section 4 changed, 1 of 5.
Sections 1, 2, 3, 5 unchanged."` — verified live against the real v1/v2 English locks.

One logged observation: v1's section 4 already named volunteers and contractors in the
duty-to-report clause, so that part of the requested amendment was already true before
this edit; the substantive new content is the 24-hour deadline itself.

**Prompt 19 — changed-section re-translation.** `amend.retranslate_changed_sections`
re-translates only the changed section(s) per affected language, carrying every unchanged
section forward byte for byte from the v1 lock's persisted verbatim text (never
re-translated — re-translating unchanged text would produce different bytes for identical
meaning and silently break the identity guarantee). One correction made from live testing:
the diff passed in must come from the SOURCE language, never the target language itself,
because a target language's v2 lock does not exist until this function creates it. Live
proof for French: sections 1, 2, 3, 5 byte-identical between v1 and v2 locks; section 4
changed; 1 operation charged. 8 tests in `tests/test_amend.py` cover this, including a
fake-client proof that the instruction sent to SuperDocs names only the changed section.

**Prompt 20 — per-country change notices.** `amend.generate_change_notice` builds the
deterministic skeleton (header, the notice's own summary line — deliberately different
wording from Prompt 18's `format_diff_report`, since this prompt specified different exact
text — quoted previous/new text pulled verbatim from locked/archived text, action required
with a computed return date, and an unconditional annexes-6–9-unchanged line, all in the
office's working language). `amend.send_change_notice` is the one billed step: it fills a
single placeholder paragraph with a plain-language "what changed" summary via one chat
call, verifies afterward that the placeholder is gone AND that every quoted before/after
section body still matches the locked/archived text verbatim (normalised) — never trusting
the response text. Live proof for Mumbai and Senegal in `evidence/notice-generation-report.md`.

**A real defect surfaced live, fixed in code, not worked around by hand:** a notice's
single billed chat call can come back billed (`usage.was_billable: true, ops_charged: 1`)
with a confused non-edit response (*"I am not sure how to help you..."*) and `changes:
null` — the exact same class of "billed but nothing changed" unreliability already
documented for pack-generation batches in `evidence/superdocs-batch-limit-report.md`, now
confirmed on a single-section document call, so it is not a batching-specific defect.
`send_change_notice` retries once (`_MAX_NOTICE_ATTEMPTS = 2`), checking the *export*
after each attempt, never the response text; a notice needing a retry honestly costs 2
operations, not the idealised 1 — the ledger records what happened, not an assumed
constant. Observed live for Mumbai (2 ops) and, in Prompt 21's full run, Nairobi (2 ops).

**Prompt 21 — re-lock, re-verify, Run 2 table.** `service.relock_v2` re-locks the core at
v2 across every language a configured country uses: the source language directly (0 ops),
every other language via `retranslate_changed_sections` (1 op the first time, 0 on rerun —
proven idempotent live with an `ExplodingClient` that would fail the test if any network
call were attempted). Portuguese was re-translated live in this prompt (French was already
done in Prompt 19); section 4 changed, sections 1/2/3/5 byte-identical to v1, exactly as
French showed.

`service.verify_after_amendment` re-verifies all five packs and confirms annexes are
untouched **without reissuing any pack**: each pack is checked against `from_version` (v1
— the version it was actually generated at), never the new `to_version`, because no pack
is reissued by an amendment. All five pass; all five have zero unlocalised annex sections.
Separately, the newly re-locked v2 core is checked for cross-language structural
consistency — `diff_core_versions` for en/fr/pt must each report the same
changed/unchanged split as the source-language diff — confirmed for all three.

**The Run 2 ledger, real and complete** (`evidence/run2-ledger.md`,
`evidence/run2-integrity-report.json`): all five change notices were generated live
(IN, SN in Prompt 20; KE, FR, BR completing the set in Prompt 21). Two needed a retry (IN,
KE); SN, FR, BR landed on the first attempt. Real total: **9 operations** (2 re-translations
+ 7 notice-generation calls), against the idealised **7** (2 + 5) — the same 2-op overrun
pattern as Phase 4's pack generation, same root cause (live SuperDocs edit-call
unreliability), now measured precisely because every call in this run was made and recorded
in this session.

**Run 1 vs. Run 2 — the equivalence the build exists to demonstrate**, idealised model:

| | Run 1 — full rollout | Run 2 — core amendment |
|---|---|---|
| Scope | 5 countries, 3 languages, 5 packs | Same 5 countries, 3 languages, **0 packs reissued** |
| Operations | 2 translations + 5 packs × 1 = **7** | 2 re-translations + 5 notices = **7** |
| What ships | 5 full policy packs | 5 short (2–3 page) change notices |

Both real runs exceeded their idealised figures for the same reason — live SuperDocs
chat-edit calls do not reliably apply on the first attempt, and a failed attempt can still
be billed. Run 1's real total was never cleanly isolated (see `evidence/ledger-summary.md`
— only a 5-op remediation round was itemised at full precision; the account's promo
counter dropped 36 ops across a session that also included unrelated prior experiments).
Run 2's real total (9 ops) **is** cleanly isolated, because every call in Prompts 19–21 was
made and recorded within this session. The idealised 7-vs-7 equivalence is the number to
put in the README; the real, itemised 9-op Run 2 total belongs beside it as the honest
"what it actually cost, including the flakiness tax."

**Fragile in the amendment path — logged, not hidden:**

1. **A notice's billed chat call can silently fail** (billed, `changes: null`, a confused
   response) — the same defect class as pack batches, now confirmed present outside
   batching too. Mitigated by bounded retry + export-based verification, never by trusting
   the response. Not eliminated: a notice could in principle exhaust `_MAX_NOTICE_ATTEMPTS`
   and raise `NoticeIntegrityError`, quarantining that one country's notice rather than
   shipping a broken one.
2. **Independent translation calls for the same clause can drift in wording even when the
   underlying English is unchanged.** Observed live in Brazil's notice: the pt v1 lock
   (translated in Phase 4) renders one clause as *"idade de consentimento local"*; the pt
   v2 lock (translated fresh in Prompt 19, since section 4 changed) renders the same
   English clause as *"idade legal de consentimento local"* — a cosmetic difference, not a
   substantive one, since the English source is byte-identical there. The model's
   plain-language summary for BR's notice ("...e especifica a idade legal de
   consentimento") is grounded in the literal displayed text delta, but could read to an
   office as if that rule changed, when only the wording of an already-true rule did. This
   is a known limitation of section-level (not clause-level) re-translation with a
   non-deterministic translator, not a bug in any single translation call. Not fixed in
   this session — would need either clause-level diffing or an explicit instruction to the
   summary call to ignore purely cosmetic wording differences.

## Phase 7 — Surfaces (Session 8, Prompts 22–24)

Both surfaces sit over `service.py` — the routes and the React screens are navigation onto
functions the CLI already calls; neither reimplements lock/generate/verify/amend.

**Prompt 22 — FastAPI routes.** `src/localizer/api/{app,routes,runs}.py`, served on 8000:
`GET /countries`, `GET /packs`, `GET /packs/{code}`, `GET /integrity`, `POST /runs/rollout`,
`POST /runs/amendment`, `GET /runs/{run_id}`, `GET /runs/{run_id}/ledger`. Long operations
never block a request: a rollout/amendment is scheduled via `BackgroundTasks` and returns a
run id immediately (proven live: ~70–100ms regardless of the underlying SuperDocs call
time); the caller polls status instead. `service.run`/`service.run_amendment` gained an
optional `ledger` parameter so the API's background-run tracker can hold the exact `Ledger`
instance a run is writing to and read live entries mid-run — proven live on the Amend screen
below, not just asserted.

**Prompt 23 — the Integrity screen.** `ui/` scaffolded with Vite + React + TypeScript.
`Integrity.tsx` is deliberately the only screen built with real design care in this prompt:
core version/pack count/languages summary, one row per language (hash, owning-pack chips,
identical/divergent state — FR and SN visibly sharing one hash), annex divergence counted
per slot, and a loud red quarantine banner that renders only when a report ever carries
`quarantined_packs` (verified with a temporary local mock, reverted before committing — the
real `evidence/integrity-report.json` has never contained a quarantined pack). No component
library, no charts, no dashboard chrome — a typographic pass (eyebrow-style section labels,
tabular numerals, consistent spacing rhythm) was its own commit.

**Prompt 24 — the remaining four screens: Countries, Generate, Packs, Amend**, plus a nav
shell (`Nav.tsx`, `react-router-dom`), a thin `api.ts` fetch wrapper, and a Vite dev-server
proxy (`/api/* → 127.0.0.1:8000`, `vite.config.ts`) so the browser never needs the backend to
configure CORS. Backend additions were kept to exactly what each screen needed and landed in
the same commit as the screen that needed them: `annex_summary` (legal instrument count,
external reporting channel count, escalation tier 1) added to `GET /countries` for the
Countries screen; a `core_hash` and `/exports/{code}/...` links added to `GET /packs` and
`GET /packs/{code}` for the Packs screen, backed by a `StaticFiles` mount of `out/` at
`/exports` in `app.py`.

**What was proven live, not just built:**
- **Countries** — real per-country divergence at a glance: Kenya shows 4 legal instruments
  against 3 everywhere else, and every escalation tier-1 line reads distinctly.
- **Packs** — India's `core_hash` displayed matches the Integrity screen's `en` hash exactly;
  its `.md` export link opens the real generated pack through the `/exports` mount.
- **Generate** — a real rollout POST, polled to an honest `ERROR` status with the exact
  "`SUPERDOCS_API_KEY` is not set" message (this dev sandbox has no key wired to its own
  process — same constraint noted since Prompt 10) and a ledger reporting `0 ops`, never a
  bluffed number.
- **Amend** — a real amendment POST against India (already amended to v2 in Prompt 21) came
  back `DONE` with the live ledger showing `[retranslate] fr SKIPPED 0 ops`,
  `[retranslate] pt SKIPPED 0 ops`, `[notice] IN SKIPPED 0 ops` — the idempotency guarantee
  observed working end to end through the UI, not asserted from code reading alone. The
  notice's `.md` link opened the real change notice (section 4 quoted before/after, the
  24-hour deadline, the annexes-unchanged line) generated live in Prompt 20.

**What the UI does not cover, logged rather than hidden:**
1. **Integrity still reads a static snapshot**, `ui/public/integrity-report.json` (a copy of
   `evidence/integrity-report.json`), not a live `GET /api/integrity` call — this was already
   flagged as a known gap when Prompt 23 shipped and was not revisited here. Every other
   screen is live.
2. **No run-cancellation control.** The API has no "kill this run" endpoint and the UI has no
   button for it; a started rollout/amendment runs to completion or failure server-side. This
   is a real gap against the brief's B2 ("survives being stopped") if read as requiring an
   in-flight cancel — what exists is idempotent *resume*, not *interrupt*: killing the whole
   API process and restarting a run with the same countries will not double-charge or
   double-generate (proven by the CLI's own "run it clean, then run it again" test in Phase
   3), but there is no way to stop a run early from the UI once started.
3. **The dev proxy is dev-only.** `vite.config.ts`'s `/api` proxy only exists under
   `npm run dev`; a production `npm run build` + static host has no backend reachable at
   `/api` unless something else (a reverse proxy, or serving both from one origin) is set up.
   Not built — out of scope for a local demo.
4. **No client-side tests.** All verification of these five screens was manual, live, in a
   real browser against the real API and real `out/`/`state/` artifacts (documented above);
   there is no React component test suite. The Python side (`tests/`, 51 tests) is unaffected
   and unchanged by this phase.
5. **No auth on the API.** Anyone who can reach port 8000 can trigger a rollout or amendment
   (which spends real SuperDocs operations) or read `/exports`. Acceptable for a local demo
   against a personal API key; not something to expose past localhost as built.
6. **Amendment notice links are constructed client-side from a filename convention**
   (`/exports/{code}/change-notice-v{from}-v{to}.md`), not returned by the API as an
   already-formed URL the way pack exports are — because `amend.send_change_notice`'s result
   still carries local filesystem `Path`s, not the `/exports`-relative form. Works because the
   convention is fixed and was proven live, but it is a convention the client knows, not a
   contract the API states.

## Phase 8 — Ship (Session 9, Prompts 25–28)

The round's final phase: README, one-command deploy, a secret/hygiene sweep, and PR prep.

**Prompt 25 — README.** Written from `PROGRESS.md`, `CLAUDE.md`, and the real
`evidence/integrity-report.json`, in five commits: what it does / setup / run commands;
SuperDocs features used + the per-language core derivation diagram; the real Run 1 and
Run 2 ledger tables; a three-row "what strong looks like → mechanism → proof" table; and
the seven logged decisions plus honest limitations. One correction made while writing it:
the ledger section initially copied the design doc's original 7-op idealised Run 1
figure, but CLAUDE.md's own economics section had already corrected a pack's idealised
cost to 2 batched operations (12 total) after the live batching-bug fix — the README now
states the corrected 12-vs-7 comparison and logs the discrepancy explicitly rather than
silently keeping the stale, symmetrical-looking 7-vs-7 figure.

**Prompt 26 — one documented command.** `Dockerfile`, `ui/Dockerfile`, `docker-compose.yml`
bring up the API (`:8000`) and UI (`:5173`) together; the UI's Vite dev-proxy target
became env-configurable (`VITE_API_PROXY_TARGET`) so it can resolve `api` by Compose
service name instead of `127.0.0.1`. Verified against a genuine clean-clone simulation
(git-tracked files copied to a scratch directory, then only the documented commands run)
rather than trusted from reading the compose file: found and fixed two real gaps before
declaring it done —
1. With no startup check, `docker compose up` reported both containers healthy while the
   API was completely unable to reach SuperDocs; the failure only surfaced minutes later,
   buried in a background rollout's poll response. Fixed with `docker-entrypoint.sh`,
   which fails fast with the exact variable name and fix before uvicorn ever binds a
   port — verified live both ways (missing key → clean exit 1 in `docker compose up`'s
   own log; a key-shaped value → starts normally).
2. Git on Windows warned it would rewrite `docker-entrypoint.sh` to CRLF on next touch,
   which would break its shebang inside the Linux container on a future checkout — caught
   and fixed forward with `.gitattributes` (`*.sh text eol=lf`) in the same session,
   before it could bite a real clone, not after.
`out/` and `state/` need no manual `mkdir` — confirmed live: Docker creates the bind-mount
targets, and the app creates them on first write. README's "How to run it" now leads with
the one-command Docker path; the original manual Python/Node setup is kept as a
documented alternative for local dev, not removed.

**Prompt 27 — secret and hygiene sweep.** Searched the full working tree and the entire
branch history (`git log --all -p`) for real API keys, real emails, real personal data,
absolute machine paths, and hardcoded per-country logic outside `config/`. Result: clean,
with one confirmed exception the user explicitly chose to leave in place — every commit's
author metadata carries the user's real email (`git config user.email`, not file content;
zero hits in any added-line diff across the whole history). `.env.example` confirmed
placeholder-only; `.env` confirmed gitignored and absent from disk. Two minor,
non-blocking notes logged: an untracked, never-committed local `.claude/settings.local.json`
carries a real SuperDocs GCS service-account address and time-limited pre-signed URLs from
live testing sessions (never entered git); `tests/fixtures/proposed-change-raw.json`
carries an opaque SuperDocs account UUID (`user_id`), not personally identifying. Sweep
found nothing requiring a code-content removal commit.

**Prompt 28 — pull request prep.** Checked the build against `CONTRIBUTING.md` line by
line: folder path (`use-cases/kathans22/policy-pack-localizer/`, matches the required
pattern exactly), scope (`git diff --stat main...HEAD` — all 80 changed files inside the
folder, zero outside), licensing (repo-root `LICENSE` is MIT; README's License section
now links to it explicitly), and all four required README sections. One small alignment
commit — the README didn't cite the repo-root license or `CONTRIBUTING.md` by name.
Everything else was already compliant; nothing was invented to fill a commit.

### What shipped

- The full pipeline: core locking, per-language translation (cached), per-country pack
  generation with batched-and-verified annex edits, deterministic acknowledgement forms,
  and the amendment path (section-level diff → per-language re-translation of only the
  changed section(s) → per-country change notice), all driven over SuperDocs MCP, all
  enforced by hash verification rather than trusted from any response.
- **The central proof, live-verified, not asserted:** France and Senegal — two countries,
  two entirely different annexes — carry byte-identical core text
  (`evidence/integrity-report.json`).
- A real, itemised Run 1 (rollout) vs. Run 2 (amendment) ledger comparison: 9 real
  operations to propagate a core change to all five offices with **zero packs
  reissued**, against a idealised-model 12 ops to stand the whole rollout up once.
- A FastAPI backend (8 routes) and a 5-screen React UI (Countries, Generate, Packs,
  Integrity, Amend), both thin layers over the same `service.py` the CLI calls — nothing
  reimplemented per surface.
- 51 passing tests against recorded fixtures and fakes, no live key required.
- One-command Docker Compose deployment, verified against an actual clean-clone
  simulation, with a fail-fast startup check naming the exact fix for a missing API key.
- A README carrying the real ledger tables, the core-derivation diagram, the
  bar-to-mechanism-to-proof table, all seven logged decisions, and an honest limitations
  section — not a feature list.

### What did not ship

- **The Integrity screen's UI reads a static snapshot file**, not a live
  `GET /api/integrity` call — the one screen out of five that isn't fully live.
- **No run-cancellation** in the API or UI — a started rollout/amendment runs to
  completion or failure; only idempotent *resume* exists, not in-flight *interrupt*.
- **No auth on the API** — acceptable for a local demo against a personal key, not for
  anything reachable past localhost.
- **No client-side (React) tests** — all five screens were verified manually, live,
  against the real API; the Python side is fully covered, the UI side is not.
- **The demo video and screenshot are still placeholders** in the README — the build
  itself is done and verified live throughout every phase, but the recorded artifact
  CONTRIBUTING.md asks for ("if you have one") was not produced in this session.
- Clause-level re-translation for amendments — section-level diffing means a purely
  cosmetic wording drift between two independent translation calls of the same unchanged
  English clause (observed live in Brazil's Portuguese notice) can read to an office as
  if a rule changed when only its wording did.

### What I would do next, with more time

1. **Wire the Integrity screen to `GET /api/integrity` live**, closing the one gap
   between it and the other four screens — it's the hero screen and the only one still
   reading a snapshot file.
2. **Parallelise `service.run` across countries.** Nothing in the design requires
   sequential per-country processing; each pack is an independent SuperDocs session. This
   is the one thing flagged in the README that would matter most at real scale (fifty
   countries would currently take roughly ten times as long, wall-clock, as five).
3. **Clause-level diffing for amendments**, or an explicit instruction to the
   change-notice summary step to ignore purely cosmetic wording deltas between two
   independent translation calls of unchanged English text — the one concrete
   translation-quality risk this build found live and documented but didn't fix.
4. **A run-cancellation endpoint and UI control**, closing the gap against B2 read as
   requiring in-flight interrupt, not just resume.
5. **Minimal API auth** (even a static bearer token) before this ever runs anywhere past
   localhost — currently anyone reaching port 8000 can spend real SuperDocs operations.
6. Record the actual demo video and take the actual screenshot the README still
   placeholders — the last purely mechanical gap before the PR is fully submission-ready.
