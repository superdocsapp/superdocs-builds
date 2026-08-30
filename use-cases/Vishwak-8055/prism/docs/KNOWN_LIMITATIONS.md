# Known Limitations

Format per the directive: WHAT / WHY / IMPACT / CURRENT BEHAVIOR / SAFE
FALLBACK / FUTURE PATH.

## 1. Environment-level: cannot be fixed by more engineering effort here

**WHAT:** Real cross-browser QA (Chrome/Edge/Firefox), real screen-reader
testing, live cloud/Office/e-signature/MCP integrations, and benchmarks
against real model-provider latency/cost. **UPDATE (this session):** a
real UI now exists (`@prism/ui`) with real, automated accessibility
checks — but those checks run axe-core's DOM-structure rules against
`jsdom`, not a real browser or screen reader. That's a genuine, useful,
narrower thing than what the directive asks for, and the distinction is
enforced in code, not just prose: `color-contrast` is explicitly disabled
in the test config (jsdom doesn't render layout, so that rule would be
meaningless there), and contrast was instead verified separately by
actually computing WCAG ratios for every text/background pair in the
palette — which caught and fixed a real failure (`--text-faint` measured
2.6-2.8:1 against its backgrounds; fixed to 5.1-5.5:1). **WHY:** This
sandbox has no browser to drive and no screen reader. **IMPACT:** Real
assistive-technology behavior (how VoiceOver/NVDA/JAWS actually announce
this UI) is unverified. Capabilities needing live external services
(PRISM BRIDGE, INBOX, SIGN, RESEARCH, PULSE, OFFICE, SIDE, PROTOCOL,
ADAPT) remain not built for the same reason as before. **CURRENT
BEHAVIOR:** `@prism/ui`'s test suite states its own scope limit in a
comment at the top of `test/accessibility.test.js`, not only in this
file. **SAFE FALLBACK:** No fake browser/screen-reader test was written
to fill the gap. **FUTURE PATH:** A real device/browser lab or CI service
(e.g. Playwright with real browser binaries, which this sandbox's network
allowlist doesn't reach) for the external integrations; a real assistive-
tech pass for the UI specifically.

## 2. Document model covers body paragraphs and tables; not headers/footers/notes/tracked changes

**WHAT:** No headers/footers, footnotes/endnotes, comments, numbering, or
tracked changes (`<w:ins>`/`<w:del>`). Tables ARE now supported (PRISM
GRID, this session): read structurally, compared structurally, and
passed through verbatim on write — but never edited or regenerated, and
only when the write doesn't also need to change paragraph count (see #2a).
**WHY:** Scope decision, evolving across sessions: paragraph fidelity
first, then table fidelity as the next-highest-value slice. **IMPACT:**
PRISM REFERENCE, PRISM REVISION, and PRISM VIS are still blocked. PRISM
GRID unblocks the common case of "a table-containing document also needs
paragraph-level edits." **CURRENT BEHAVIOR:** `readDocx` reports
`hasTables` and a real `tables[]` array (rows, cells, merge spans via
gridSpan/vMerge, cell text); `writeDocx` reconstructs the body in true
document order (see #2a for how) rather than refusing outright.
**SAFE FALLBACK:** Verbatim pass-through, never edited content —
correctness is "unchanged," not "correctly changed," which is the safe
default before table editing exists. **FUTURE PATH:** Table content
editing itself (currently: read + compare + preserve, not edit) is the
next slice, followed by headers/footers/notes.

### 2a. Table write-back requires paragraph count to be unchanged

**WHAT:** `writeDocx` anchors each table to "comes after N paragraphs" in
the original document. If the new paragraph sequence has a different
length (a structural add/remove was approved), that anchor is no longer
well-defined, and `writeDocx` refuses rather than guessing a new position.
**WHY:** A precise, honest boundary — see docs/DECISIONS.md for why
similarity-scored re-anchoring wasn't attempted this session. **IMPACT:**
A document with both a table AND an approved structural change cannot be
written back yet. Content/formatting edits alongside tables work fine
(paragraph count unchanged). **CURRENT BEHAVIOR:** Refuses with a message
naming the specific paragraph-count mismatch, not a generic error — tested
directly (`write-docx.test.js`, `@prism/ui/test/server.test.js`).
**SAFE FALLBACK:** Refusal, not silent mis-placement of the table.
**FUTURE PATH:** Anchor tables to a stable paragraph identity (e.g. a
op-index reference, which `@prism/delta`'s report already tracks) rather
than a raw ordinal count, so insertions/deletions elsewhere don't invalidate
the anchor.

## 3. No model/LLM is wired in anywhere

**WHAT:** Every classification, every routing decision, every "why this
matters" judgment in this codebase is deterministic (regex, set
comparison, fingerprint comparison). **WHY:** This package is meant to run
offline from a zip with no guaranteed API key or network access; a silent
no-op model call was judged worse than an honest "this needs review" flag.
**IMPACT:** PRISM NEXUS, PROOF, TARGET, ADAPT, JUDGE, AGENTDESK, and
CONTINUUM all need this tier and are not built. **CURRENT BEHAVIOR:**
DELTA's `semantic` category and GATE's decision inputs are exactly where a
model would plug in, left as documented extension points.
**SAFE FALLBACK:** Route to `review-required` / require an explicit human
decision, never guess. **FUTURE PATH:** A `ClassifierAdapter`-style
interface (not yet built) that this session's deterministic logic would
become the *default implementation* of, not be replaced by.

## 4. `@prism/vault` is in-memory only

**WHAT:** No persistence layer. **WHY:** Out of scope this session — see
RISK_REGISTER #10. **IMPACT:** Version history does not survive a process
restart; PRISM MEMORY (session persistence/search) cannot be built on top
of it yet. **CURRENT BEHAVIOR:** Full version graph is queryable
(`vault.graph()`) for the lifetime of the process. **SAFE FALLBACK:** None
needed — this is additive scope, not a correctness gap. **FUTURE PATH:** A
storage adapter behind the same `Vault` interface (SQLite would be a
reasonable first target — no native compilation risk avoided if using a
pure-JS driver).

## 5. Paragraph-modification pairing is positional, not similarity-scored

**WHAT:** `alignParagraphs` pairs an immediately-adjacent removed-block
with an immediately-adjacent added-block. **WHY:** A real, tested
heuristic; similarity-scored alignment (e.g. token-overlap + optimal
assignment) is more correct but wasn't built. **IMPACT:** A paragraph that
moves to a non-adjacent position will show as an unrelated delete+insert
rather than "moved." **CURRENT BEHAVIOR:** Tested directly for the
uneven-length case it does handle correctly. **SAFE FALLBACK:** Still
surfaces as a change requiring review — never silently dropped, just
possibly mis-categorized as add+remove instead of modify. **FUTURE PATH:**
Token-overlap similarity matrix + Hungarian assignment.

## 6. No fuzzing, no adversarial input corpus, no scale testing

**WHAT:** The full adversarial test matrix the directive specifies (empty
document, huge document, corrupt document, unsupported format, network
timeout, storage failure, malicious prompt injection, etc.) is not run.
**WHY:** Not started this session — see RISK_REGISTER #7 and
docs/RISK_REGISTER.md generally. **IMPACT:** Correctness on the tested
paths (the fixture pair, one table-containing document) is real;
correctness on adversarial or large-scale input is unverified, not
verified-safe. **CURRENT BEHAVIOR:** Errors that do occur (missing file,
unknown change id, illegal workflow transition) throw with specific,
actionable messages — the error-handling *quality* on the paths that are
tested is real, even though the *coverage* of paths is narrow.
**SAFE FALLBACK:** N/A. **FUTURE PATH:** docs/RISK_REGISTER.md's
recommended-evolution items, plus a dedicated adversarial fixture set
(PRISM TRUTHSET, also not built).

## 7. The UI is a real single-operator local tool, not a multi-tenant service

**WHAT:** `@prism/ui`'s server holds one shared in-memory workspace (one
report, one approval set, one Vault) for the whole process — two browser
tabs share the same state, and a server restart loses everything not yet
committed to a version. **WHY:** Out of scope this session — see
docs/DECISIONS.md. **IMPACT:** Not suitable for multiple simultaneous
users. Temp files written per comparison (`os.tmpdir()/prism-ui-*`) are
not automatically cleaned up between runs within a process lifetime, only
cleared by `resetWorkspace()`. **CURRENT BEHAVIOR:** Explicit and tested
(`server.test.js`'s `beforeEach` calls `resetWorkspace()` precisely
because state is shared). **SAFE FALLBACK:** None needed for the intended
single-operator use. **FUTURE PATH:** Per-session workspace keyed by a
session ID/cookie, and a temp-file reaper — neither built.
