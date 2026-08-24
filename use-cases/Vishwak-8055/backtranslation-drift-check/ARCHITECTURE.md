# Architecture

## The one rule everything else follows

**Deterministic wherever correctness can be deterministic; AI only where
semantic interpretation is genuinely required — and the AI is never the sole
authority for a finding's existence when a deterministic check could
corroborate it.**

Concretely, this project implements independent regex/rule-based detectors
for 8 of the spec's drift categories (negation, modal obligation, numeric,
date, percentage, unit, qualifier, named entity) and relies on the AI
semantic layer only for the residual case: meaning drift that changes no
number, modal, negation, qualifier, or (regex-detectable) entity — see the
flagship demo's Section 12 (capillary → venous blood sample) for a concrete
example of exactly that residual case.

## Pipeline stages

```
source text ──▶ parse ──▶ hash/snapshot ─────────────────────┐
target text ──▶ parse ──▶ align sections                     │ verified at
                    │                                         │ every
                    ▼                                         │ checkpoint
      per section pair:                                       │
        provider.analyze() → back-translation + semantic read │
        deterministic signals(source, back-translation)       │
        group signals by category → aggregate into findings   │
        semantic agreement with an existing category →        │
          corroborate that finding (not a new one)            │
        cache under content hash (resumability)                │
                    │                                         │
                    ▼                                         │
              bilingual report  ◀── integrity re-verified ────┘
```

Each stage is independently testable and independently callable — nothing
here requires the whole pipeline to run to exercise one stage (see the test
suite: `test_signals_regression.py` never touches the pipeline at all,
`test_integrity.py` never touches a provider).

## Why signals are aggregated before a finding is built

Two or more deterministic signals can point at the same underlying problem —
both numbers in a "2°C to 8°C" range having their unit swapped is one
mistranslation, not two. `drift_engine._group_signals_by_category` groups
same-category signals for a section before constructing a `DriftFinding`, so
the result is one finding with multiple `Evidence` entries (severity = max
across the group, full detail preserved per-signal) rather than one finding
per signal inflating the report's count. Signals in different categories are
never merged — a modal change and a qualifier change in the same section are
genuinely different problems and stay as separate findings. See
DECISIONS.md #10.

## Why the deterministic and semantic passes are independent

`TranslationAnalysisProvider.analyze()` does **not** take the deterministic
signals as input, and the deterministic signals are computed **after** the
provider call, not before. Two consequences follow from this, one
architectural and one epistemic:

- **Architectural**: it resolves what would otherwise be a circular
  dependency — the deterministic signals compare source text to
  back-translation text, and the back-translation doesn't exist until the
  provider call returns.
- **Epistemic**: the AI's semantic read is never primed by what the regex
  layer already found. If both flag the same section, that is two
  independent methods agreeing, not one method being told the answer by the
  other and confirming it. `DriftFinding.semantic_corroborated` records
  exactly this — see the flagship demo's Section 11.

## Why back-translation + semantic assessment is one provider call, not two

Back-translating a section is unavoidable — it's the mechanism the whole
tool is built on. Given that call is already happening, attaching the
semantic judgment to the same response (rather than issuing a second call)
halves the section-level API cost with no loss of independence from the
deterministic layer, since the deterministic layer never enters this call
either way. See DECISIONS.md #7.

## Severity vs. review gating are different questions, on purpose

A finding's severity reflects how serious the drift is on its merits.
Whether it started in `PENDING_REVIEW` or the stricter `REVIEW_REQUIRED`
reflects how much scrutiny it needs before a human approves it. These are
computed independently in `severity.py`; conflating them (e.g. capping
AI-only findings at MEDIUM severity) was considered and rejected — see
DECISIONS.md #4 for why.

## Why unit changes go through a conversion policy, not a string compare

A unit token changing (°C → °F) is not automatically a drift: it might be a
correct, meaning-preserving localization. `signals/numeric.py` maintains an
explicit table of supported conversions with their formulas; a unit change
is only accepted silently when the pair is in that table *and* the
converted value matches within a rounding tolerance. An unsupported pair is
flagged for human review rather than either accepted or auto-corrected —
the system never invents a conversion it hasn't been told is correct, and
never rewrites a value on the strength of its own guess. See DECISIONS.md
#11 and LIMITATIONS.md #9.

## What's deliberately not built

Section 25 of the originating spec ("standout" Tier-3 features) is out of
scope for this build — see LIMITATIONS.md #7. A live SuperDocs client is
also out of scope, for a different reason: no real API to build one against
was available (LIMITATIONS.md #8) — but the integration seam itself
(`superdocs.py`) is built, tested, and used by every local demo. The core
(Tiers 1–2 in the spec's own priority ordering) is complete, tested, and
runs end to end on two independent demo documents.
