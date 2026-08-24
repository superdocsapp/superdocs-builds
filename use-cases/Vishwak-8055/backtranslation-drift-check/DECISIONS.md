# Design Decisions

Numbered so other docs can reference them. Each is a place the spec was
ambiguous or left room for judgment, and what was chosen.

**1. Markdown with `##` headings as the document format, single-level
sectioning.** No existing repository/format was specified. `##`-delimited
sections give stable, human-readable section IDs and are trivial to author
for the demo documents; deeper heading levels are folded into the enclosing
section's body rather than creating sub-sections. See LIMITATIONS.md #1.

**2. `Section.index` (stable ordinal), not `Section.id` (heading-derived
slug), is the authoritative key for provider/fixture lookups.** IDs are
built from heading text for readability in reports, but heading text is
translated and therefore not something a fixture file (or a cache key)
should have to reproduce exactly. Index is language-invariant and assigned
purely by document order.

**3. Alignment is positional, with an explicit `review_required` escape
hatch, never a semantic guess.** Reliable exactly when section count and
order match between source and translation (true for the vast majority of
real localization workflows). When it doesn't hold, every resulting pair is
flagged for review rather than the aligner inventing a cross-lingual
heading-similarity heuristic it can't actually validate.

**4. AI-only findings are not severity-capped; they get a stricter review
gate instead.** Considered capping semantic-only findings at MEDIUM
severity (since "the LLM must not be the sole authority for critical
checks"), and rejected it: a reviewer triaging by severity could skip a
genuinely critical issue that only the semantic layer caught (see the
flagship demo's capillary/venous finding, which is CRITICAL and
`verified_deterministically=False`). The actual safety property — nothing
is ever auto-applied — is enforced by the review workflow, not by
mislabeling severity. What *does* change is the starting `review_status`:
AI-only and alignment-uncertain findings start in `REVIEW_REQUIRED` rather
than `PENDING_REVIEW`, which is a real, meaningful distinction a reviewer's
queue can filter on.

**5. Qualifiers are split into "high-weight" (at least/at most/only/
exclusively/no later than/unless/except/solely → HIGH) and "low-weight"
(approximately/generally/roughly/up to/typically → MEDIUM).** The spec's own
taxonomy draws this HIGH/MEDIUM line but doesn't enumerate which qualifiers
land where; the split here is by whether the qualifier bounds scope/min/max
(changes what a clause actually requires) versus softens tone (changes how
a clause reads, not what it requires).

**6. Numeric severity: dates and safety/dosage-adjacent numbers → CRITICAL;
unit changes → CRITICAL; general commercial numbers (fees, ordinary
deadlines) → HIGH.** "Safety-adjacent" is a keyword-proximity heuristic
(mg/mL/°C/°F/dose/dosage/regulatory/authority/law/safety/incident/penalty
within ~60 characters) — deliberately conservative (biased toward flagging
too much rather than too little in this specific band), documented rather
than hidden in an unexplained threshold.

**7. Back-translation and semantic assessment are one provider call, not
two.** See ARCHITECTURE.md. This is a cost-discipline decision (spec section
17: "do not repeatedly call an LLM... use AI only where it creates actual
value") that also happens to keep the deterministic and semantic passes
cleanly independent (see decision below).

**8. The deterministic and semantic detection passes never see each other's
output before producing their own.** `TranslationAnalysisProvider.analyze()`
does not take deterministic signals as input. Rejected an earlier draft
where it did (to "give the LLM context") once it became clear that (a) it's
circular — signals need the back-translation the call produces — and (b) it
would have made "corroboration" meaningless, since the AI would have been
primed by the thing it's supposed to independently corroborate.

**9. Corrections are literal find/replace only for language-invariant
tokens (digits); everything else is a natural-language instruction.**
Auto-generating replacement *prose* in the target language for a modal,
negation, qualifier, or entity change would mean this system silently
performing the translation work it exists to check — the exact failure mode
it's built to catch, just self-inflicted. See LIMITATIONS.md #6.

**10. Same-category deterministic signals within a section are aggregated
into one finding with multiple evidence items; different-category signals
are never merged.** An earlier version of this codebase left same-category
signals as separate findings (documented at the time as an accepted
trade-off). Revisited during a pre-submission audit: two numbers in one
temperature range both having their unit swapped is one mistranslation, and
reporting it as two inflates the finding count without adding information a
reviewer needs. `drift_engine._group_signals_by_category` now groups before
constructing a finding; severity is the max across the group, and every
contributing signal keeps its own `Evidence` entry, so no detail is lost —
only the count is. A modal change and a qualifier change in the same
section are genuinely different problems and are never merged into each
other, aggregation only ever collapses multiple signals *of the same
category*.

**11. Unit changes are checked against an explicit conversion table with a
rounding tolerance, not compared as raw unit-token strings.** Without this,
a translator correctly localizing "2°C" to "35.6°F" would be
indistinguishable from the dangerous bug of leaving "2°C" as "2°F" — both
change the unit token. The policy: (a) if the unit pair is in the supported
table and the converted value matches within `max(0.5, 3% of expected)`,
it's a legitimate conversion and produces no finding; (b) if the pair is
supported but the value doesn't match, that's flagged CRITICAL as an
incorrect conversion — arguably more dangerous than a flat swap, since it
looks like someone attempted a conversion and got the arithmetic wrong; (c)
if the pair isn't in the table at all, it's flagged for human review with
no value ever auto-rewritten. The table itself is intentionally narrow
(°C↔°F, g↔kg↔mg, mL↔L, km↔miles — the exact units the spec names) rather
than a general-purpose unit library, so every supported conversion is one a
human reviewer of this code can verify by reading the formula.

**12. The SuperDocs integration is a real, tested adapter *interface* with
a local/offline implementation, not a live client.** No SuperDocs API
specification or credentials were discoverable in this environment. Rather
than skip the integration entirely or fabricate a client against an
imagined API, `superdocs.py` defines the `SuperDocsAdapter` protocol
(upload / propose-edit / record-review-decision / export) that a real
integration would need, backed by `LocalSuperDocsAdapter`, which implements
those exact operations against the local filesystem. `live_status()` and
`credential_status()` both always report `PENDING_NOT_CONFIGURED` rather
than a fabricated `VERIFIED` — there has never been a real network call
here to justify that status.
