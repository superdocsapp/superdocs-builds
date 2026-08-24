> Built by Vishwak Teja Ravula for the SuperDocs Engineer Task — Back-Translation Drift Check.
# Back-Translation Drift Check

A localization QA tool for regulated / high-stakes documents. It takes a
source document and its translation, back-translates the translation
section-by-section, and flags places where the back-translation's meaning
diverges from the source â€” negated obligations, changed numbers/dates/
percentages/units, dropped scope qualifiers, altered named entities, and
subtler semantic drift a regex can't catch. It never touches the source,
every correction it proposes targets the translation, and every finding
goes through explicit human review before anything is considered accepted.

**Stack note:** this is a Python package (`pyproject.toml`, `pytest`,
`mypy`, `ruff`), not a Node/npm project â€” there's no `package.json` and no
running server. The pipeline produces a static HTML report â€” no external
JS, no external data calls, and it degrades cleanly to system fonts if
offline, but its CSS does load decorative webfonts from Google Fonts over
the network when available. Open it directly in a browser.
See "Running it" below for the exact commands.

## The problem

You can't directly compare a source sentence to its translation unless you
read both languages. Back-translating the translation into the source
language turns every comparison into a same-language comparison, which lets
cheap deterministic rules (regex, numeric extraction, unit-conversion
arithmetic) and an LLM's semantic judgment both operate on it â€” critically,
*independently*, so one can corroborate or catch what the other misses.

## Architecture

```
SOURCE â”€â”€â–¶ PARSE â”€â”€â–¶ SECTION ALIGNMENT
                          â”‚
TARGET â”€â”€â–¶ PARSE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                          â”‚
              per section pair:
                BACK TRANSLATION (provider call)
                          â”‚
        â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”´â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
        â–¼                                     â–¼
 DETERMINISTIC SIGNALS                SEMANTIC ASSESSMENT
 (regex/rule, independent)         (LLM, independent â€” never
                                     primed by the signals)
        â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
                           â–¼
          SIGNAL CORROBORATION / AGGREGATION
   (same-category signals â†’ one finding, many evidence items;
    semantic agreement with an existing category â†’ corroboration,
    not a duplicate finding)
                           â–¼
                       SEVERITY
                           â–¼
                    HUMAN REVIEW
              (approve / reject / edit)
                           â–¼
            TRANSLATION-ONLY CORRECTION
                           â–¼
          SOURCE INTEGRITY VERIFICATION
           (re-checked at every stage)
                           â–¼
                        REPORT
```

Modules (`src/drift_check/`):

| Module | Responsibility |
|---|---|
| `models.py` | Typed data model (Document, Section, DriftFinding, etc.) |
| `parsing.py` | Deterministic heading-based section identification |
| `integrity.py` | Source hashing, snapshotting, mutation detection |
| `alignment.py` | Positional section alignment with review-required fallback |
| `signals/` | Deterministic detectors: modal/negation, numeric/date/%/unit (with conversion policy), entities |
| `providers/` | `FixtureProvider` (offline) and `AnthropicProvider` (live), behind one Protocol |
| `drift_engine.py` | Aggregates deterministic signals + semantic assessment into findings |
| `severity.py` | Severity and review-status policy |
| `correction.py` | Proposed corrections â€” always translation-targeted |
| `review.py` | Approve/reject/edit workflow, never auto-applies |
| `superdocs.py` | SuperDocs integration seam â€” local/offline adapter today, see below |
| `audit.py` | Append-only structured audit trail |
| `pipeline.py` | Orchestration, resumability, idempotency |
| `report.py` | Markdown / JSON / HTML bilingual report |
| `cli.py` | `drift-check run` / `drift-check review` |

## Detection model

Deterministic wherever correctness can be deterministic; the LLM only where
semantic interpretation is genuinely required, and never as the sole
authority when a deterministic check can corroborate a finding.

Independent regex/rule detectors exist for 8 of the categories below;
everything else (subtler meaning shifts that touch no number, modal,
negation, qualifier, or regex-detectable entity) is the semantic layer's
job â€” see the flagship demo's Section 12 for a concrete example of exactly
that residual case.

| Category | Mechanism |
|---|---|
| Modal obligation (must/should/may/shall, softened/reversed) | Deterministic â€” obligation-strength scale, flags any tier change |
| Negation (lost/added, outside modal phrases) | Deterministic â€” marker-count comparison |
| Numbers, percentages | Deterministic â€” extraction + positional pairing |
| Dates | Deterministic â€” Month DD YYYY / DD Month YYYY / ISO parsing |
| Units | Deterministic â€” **explicit conversion policy** (below), never a raw string compare |
| Qualifiers (at least/only/unless/â€¦) | Deterministic â€” high/low-weight tiers |
| Named entities | Deterministic (protected-term exact match + capitalized-phrase heuristic) *and* semantic |
| Everything else | Semantic (LLM), independently corroborated when a deterministic signal also fires |

**Finding aggregation.** Multiple low-level signals about one underlying
problem are combined into one finding with multiple evidence items, not
reported as separate defects â€” e.g. a temperature range with two numbers
that both had their unit swapped is one `unit_change` finding with two
pieces of evidence, not two. Signals in genuinely different categories (a
modal change and a qualifier change in the same section) stay as separate
findings, because they're separate problems. Full detail is never dropped â€”
every contributing signal keeps its own evidence entry.

**Unit-conversion policy.** A unit change is not treated as a flat string
mismatch. If the target unit is a supported conversion of the source unit
(Â°Câ†”Â°F, gâ†”kgâ†”mg, mLâ†”L, kmâ†”miles) *and* the converted value matches within a
rounding tolerance, it's a legitimate localization and passes cleanly â€” no
finding. If the unit changed but the value doesn't match a correct
conversion, that's flagged CRITICAL as a wrong conversion. If the unit pair
isn't in the supported list at all, it's flagged for human review rather
than silently accepted or silently rewritten â€” the system never guesses a
conversion it hasn't been told is correct.

## Source integrity

Every run hashes the source document (whole-document and per-section) once,
immediately after reading it, and re-verifies that hash at every subsequent
pipeline checkpoint â€” 14 checkpoints on the flagship demo. A deliberate
mutation test (`tests/test_integrity.py`) snapshots a source, mutates it in
memory, and confirms the guard raises. The CLI's `run` command never opens
the source file for writing, which is asserted directly in the same test
file by checking the file's bytes and mtime are unchanged after a full run.

## Human review

Every finding starts in one of two states â€” `PENDING_REVIEW` for
deterministic-backed findings, the stricter `REVIEW_REQUIRED` for findings
that rest on the semantic layer alone or on an uncertain section alignment â€”
and only ever changes through an explicit `approve` / `reject` / `edit`
call naming a reviewer (`review.py`). Editing records the reviewer's final
text on the review decision without mutating the system's original
proposal, so an audit can see both what was suggested and what was actually
used. Nothing is ever auto-applied.

The generated HTML report (open any `*.html` file under `out/` after a run)
renders each finding as a card: source, translation, and back-translation
side by side, the detected drift, a translation-only proposed correction,
and Approve / Reject / Edit controls. Those controls are demonstration UI â€”
they update the visible status client-side but don't persist anywhere;
recording a real decision goes through `drift-check review` or `review.py`
directly.

## SuperDocs integration

`superdocs.py` defines the adapter interface a real integration would need
(upload, propose-edit, record-review-decision, export) and a
`LocalSuperDocsAdapter` that implements those operations against the local
filesystem â€” what every test and demo in this project actually exercises.

**LIVE INTEGRATION: PENDING / NOT CONFIGURED.** No SuperDocs API
specification or credentials were available to build or test against, so
there is no remote client here to claim works â€” `credential_status()`
reports this explicitly rather than a fabricated success. The adapter seam
is real; a `RemoteSuperDocsAdapter` implementing the same protocol against
the actual API is the only thing that would need to be added once its
contract is known.

## Testing / evaluation

### Verification evidence

The flagship demonstration processes all 12 sections and produces 13 findings:

- **5 critical**
- **6 high**
- **2 informational/pass**
- **0 medium**
- **0 low**
- **Source integrity:** VERIFIED
- **Integrity checkpoints:** 14
- **Provider calls:** 12
- **Provider retries:** 0

Automated quality checks:

- **Pytest:** 87 tests collected â€” 86 passed, 1 known parity regression
- **mypy:** PASS â€” no issues found in 23 source files
- **Ruff:** PASS â€” all checks passed
- **Git diff check:** PASS

Visual and execution evidence:

- [`01-critical-modal-obligation.png`](docs/evidence/01-critical-modal-obligation.png)
- [`02-named-entity-drift.png`](docs/evidence/02-named-entity-drift.png)
- [`03-verification-quality.png`](docs/evidence/03-verification-quality.png)



```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e . && pip install pytest mypy ruff

python -m pytest tests/ -q                                   # 87 tests
MYPYPATH=src mypy -p drift_check --explicit-package-bases     # typecheck, clean
ruff check src/ tests/ scripts/                                # lint, clean
```

All tests run against `FixtureProvider` â€” zero API credentials required,
zero network calls made. See TESTING.md for the full coverage map and
DEVELOPMENT_LOG.md for the real bugs this suite caught during development
(a category-mislabeling bug and a frozen-dataclass mutation bug, both fixed
before this was considered done).

## Demo

`fixtures/flagship/` is a synthetic 12-section medical-device + financial
agreement (English â†’ Spanish) seeded with all 10 cases the spec's flagship-
demo section lists by name: 8 deliberate errors (modal reversal, modal
softening, a numeric change, a date change, a percentage change, a unit
change, a dropped qualifier, an altered named entity) plus 2 deliberate
non-errors that must PASS (a legitimate synonym, a harmless reorder) â€” plus two bonus sections showing the
deterministic and semantic layers corroborating each other and, separately,
the semantic layer alone catching a drift (capillary â†’ venous blood sample)
no regex in this codebase can see. `fixtures/second_doc/` is an unrelated
4-section HR policy (English â†’ French) proving the pipeline isn't hardcoded
to the flagship domain or language pair.

## Running it

```bash
drift-check run --source fixtures/flagship/source_en.md --target fixtures/flagship/target_es.md \
  --source-lang en --target-lang es --run-id demo --provider fixture \
  --fixture-file fixtures/flagship/back_translations.json \
  --protected-terms "MedSure Compliance Board (MCB)" --out-dir out

python3 -m http.server -d out 8000   # then open http://localhost:8000/demo.html
```

This writes `out/demo.json`, `out/demo.md`, and `out/demo.html`. To run
against the real Anthropic API instead of fixtures, set `ANTHROPIC_API_KEY`
and pass `--provider anthropic` â€” see LIMITATIONS.md #5 for what is and
isn't verified about that path in this build.

## Documentation

ARCHITECTURE.md (the deterministic/AI split in depth), DECISIONS.md
(specific judgment calls and why), LIMITATIONS.md (explicit scope
boundaries), TESTING.md (coverage map), DEVELOPMENT_LOG.md (build history
including the bugs caught along the way).

## Evidence

- [Critical modal obligation drift](docs/evidence/01-critical-modal-obligation.png)
- [Named-entity drift](docs/evidence/02-named-entity-drift.png)
- [Verification and integrity](docs/evidence/03-verification-quality.png)
