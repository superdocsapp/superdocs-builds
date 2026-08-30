# Architecture

## Layering

```
┌─────────────────────────────────────────────────────────────────┐
│ UI — src/components/**                                          │
│ One React component per concern. Pages compose tabs; tabs       │
│ compose small presentational pieces (RiskFactorList,             │
│ ProvenanceThread, DocumentReadingPane…) that take plain props    │
│ and render — no component reaches into the store on its own      │
│ unless it needs to trigger a reviewer action.                    │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ reads documents / calls actions
┌───────────────────────────────▼───────────────────────────────────┐
│ Application state — src/store/appStore.ts (Zustand)               │
│ Single source of truth for `documents`, plus cross-cutting UI     │
│ state (toasts, command-palette open/closed). Every mutating       │
│ action: (1) updates the affected document immutably, (2) appends  │
│ a ReviewEvent describing what happened, (3) usually pushes a      │
│ toast. The audit trail is a side effect of the action, not a      │
│ separate logging concern someone can forget to wire up.           │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ shaped like
┌───────────────────────────────▼───────────────────────────────────┐
│ Domain model — src/types/domain.ts                                 │
│ Plain, serializable, framework-agnostic types. SDDocument is the   │
│ aggregate; everything else (Claim, Evidence, Requirement, Risk,    │
│ Decision, ActionItem, ChangeEvent, ReviewEvent, ProvenanceRecord)  │
│ hangs off it by id, not by nested ownership, so any entity can be  │
│ found, cross-referenced, and unit-tested independently.            │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ scored/derived by
┌───────────────────────────────▼───────────────────────────────────┐
│ Domain logic — src/domain/*.ts                                     │
│ Pure functions, zero React/store dependencies, 100% unit-testable: │
│ computeCompliance, computeRisk, computeClaimsSummary,               │
│ evaluateStaleness, summarizeChange, traceClaim, runSearch,          │
│ computeAttentionItems / computeDashboardMetrics.                   │
└───────────────────────────────┬───────────────────────────────────┘
                                 │ designed to be produced by
┌───────────────────────────────▼───────────────────────────────────┐
│ Intelligence services — src/services/intelligence/                 │
│ Typed interfaces (ClaimExtractionService, RiskAnalysisService,      │
│ ReviewRecommendationService, …) with one deterministic mock         │
│ implementation. The Risk tab calls reviewRecommendation.recommend() │
│ live; the rest are wired for a real backend to implement later.     │
└─────────────────────────────────────────────────────────────────┘
```

## Why derived numbers are never stored

`SDDocument` has no `confidence`, `complianceScore`, or `riskLevel` field. This was a
deliberate constraint, not an oversight. If those numbers were authored alongside the
seed data, two things would go wrong: (1) they'd drift out of sync with the underlying
claims/requirements/risks the moment anyone edited the fixtures, and (2) the UI would
have nothing to *explain itself with* — "why is this 67%?" would have no answer.
Instead, every score is a pure function of the facts:

```ts
computeCompliance(document.requirements)   // → { scorePercent, satisfied, warnings, failures, byCategory }
computeRisk(document)                       // → { level, score, factors: [{ category, count, label }] }
computeClaimsSummary(document.claims)       // → { overallConfidence, evidenceCoveragePercent, ... }
```

This is also exactly the shape a real backend would need to fill: a claim-extraction
model doesn't need to also decide "is this document 67% compliant" — that's arithmetic
over whatever claims/requirements come back. Keeping the arithmetic in a pure, tested
function means the extraction backend and the scoring logic can evolve independently.

## Walking one action end-to-end

Take "a reviewer clicks *Mark resolved* on a risk finding":

1. `RiskTab` calls `resolveRisk(document.id, risk.id)` from the store.
2. The store finds the matching document, maps `risk.status` to `"Mitigated"` (a new
   array, new object — never mutated in place), appends a `ReviewEvent` of type
   `"Finding Resolved"` with a human-readable explanation, and pushes a success toast.
3. `useDocument(id)` — a Zustand selector — returns a new object reference, so every
   component reading that document re-renders: the Risk tab's factor list drops the
   resolved item, the Reality tab's risk score updates, the Dashboard's attention feed
   (if visited) no longer surfaces it, and the Timeline tab gains the new event —
   all from one store update, with no manual cache invalidation anywhere.
4. The original seed object in `SEED_DOCUMENTS` is untouched, because every step used
   immutable updates. This is what `appStore.test.ts` asserts directly.

## State management split

Two kinds of state, deliberately kept apart:

- **Cross-cutting / shared** → the Zustand store: the documents themselves, toasts, and
  command-palette visibility. Anything more than one screen needs to see or that
  survives navigating away and back.
- **Page-local / ephemeral** → `useState` in the component that owns it: search text,
  active filter chips, which action is being reassigned, a draft comment. This is never
  needed elsewhere and doesn't need to survive a route change.

The alternative — putting everything in the global store — would make the store a junk
drawer and make it harder to reason about what's actually shared. The alternative in the
other direction — no global store, prop-drilling documents everywhere — would make the
reviewer actions (which need to reach from a deeply nested drawer button back up to the
document list) much messier than a store subscription.

## Information architecture: why six nav items, not ten

The brief's suggested IA lists Evidence, Requirements, Risks, Changes, Decisions, and
Actions as separate top-level sections. In practice, every one of those is richest **in
the context of one document** — "show me all evidence" across a six-document workspace
with no document context is a much weaker screen than "show me this contract's
evidence, next to its claims." So:

- **Claims, Evidence, Requirements, Changes, Decisions, and Actions** live as tabs on
  the Document Reality page, where they have full context and can cross-reference each
  other (a risk factor links straight to the requirement that caused it).
- **Reviews, Risk, and Audit** get dedicated global pages, because "what's waiting on
  me across everything" and "what's the worst open finding anywhere" are genuinely
  useful rolled up across documents.
- **Command Center** covers the rest: any entity, from any document, one search away.

This is six well-developed surfaces instead of ten shallow ones, which is the tradeoff
the build brief explicitly invites ("improve the structure if your product reasoning
suggests something stronger").

## Visual design system

The brief for a document-verification product is "precision, trust, intelligence" — the
easy failure mode is generic SaaS-dashboard styling (purple gradients, big-number KPI
cards, rounded-everything cards) that says nothing about what the product actually does.
The direction taken here is grounded in the product's own subject matter: chain of
custody, notarization, ledgers, blueprints.

- **Color** is functional before it's decorative. Four hues carry the entire
  verification vocabulary: a teal-green ("verified"/"satisfied"/low risk), an
  ochre/amber ("partial"/"warning"/medium risk), an oxblood red ("contradicted"/
  "failed"/high-critical risk), and a neutral slate (not yet evaluated). A
  blueprint-ink blue is reserved for the product's own actions (links, primary
  buttons, focus rings) — never used for a status.
- **The verification grammar (`VerificationDot`)**: solid fill means *evaluated*, and
  the color carries the result; a hollow, dashed ring means *not yet evaluated*. This
  is used identically for claims, and is the same idea a broken provenance link uses.
  It's a shape-based signal that doesn't depend on color alone (a real accessibility
  win, not just an aesthetic one).
- **The signature element — `ProvenanceThread`**: a literal chain-of-custody
  visualization (Claim → Evidence → Source → Verification) used in the claim detail
  drawer. A missing link renders as a dashed connector into a hollow, alert-colored
  node — the chain visibly *breaks* instead of quietly omitting a step. This is the
  single element the product should be remembered by, because it's the most literal
  possible rendering of the product's own thesis.
- **Type** is one superfamily (IBM Plex) doing three distinct jobs: **Serif** for the
  document's own words (the reading pane — this is deliberately the only serif text in
  the product, so it always reads as "this is the source"), **Sans** for the product's
  chrome, and **Mono** for anything numeric or identifier-shaped (ids, timestamps,
  percentages, scores) — giving data a calibrated, instrument-panel feel.
- **Motion** is restrained and meaningful: panel/drawer transitions, a settle on the
  progress rings, nothing decorative. Every animation is disabled under
  `prefers-reduced-motion` via one global rule in `index.css`, rather than being
  re-implemented per component.

## Accessibility

- Semantic landmarks and a skip-to-content link in `AppShell`.
- `Tabs` implements the full roving-tabindex + arrow-key pattern per the WAI-ARIA tabs
  pattern, not just `onClick` handlers with `div`s.
- `Drawer`, `Modal`, and `CommandPalette` all share one `useFocusTrap` hook: focus moves
  into the panel on open, Tab/Shift+Tab cycle within it, Escape closes it, and focus
  returns to whatever opened it.
- Status is never color-only: every badge carries text, and the verification dots carry
  an accessible name via `aria-label` in addition to their shape/color.
- Global focus-visible ring, sufficient contrast (the palette was chosen against a white
  surface, not assumed), and a `prefers-reduced-motion` rule applied once, globally.

## Testing strategy

Three layers, matched to what's cheap to get right at each level:

- **Domain logic** (`src/test/domain`) — pure-function tests against both synthetic
  fixtures (to pin exact arithmetic: thresholds, pluralization, sort order) and the real
  seed documents (so the hand-authored demo data is itself under test — if someone edits
  the Ironclad MSA fixture and accidentally breaks the "High risk" story, a test fails).
- **Store** (`src/test/store`) — every reviewer action, asserting both the state change
  and the audit-trail side effect, and that seed data is never mutated in place.
- **Components** (`src/test/components`) — React Testing Library exercising real user
  flows: opening a claim and verifying it, resolving a risk, the approve/request-changes
  dialogs, command-palette search-and-navigate, Escape-to-close. These catch the class of
  bug unit tests can't: wiring between the store, routing, and the rendered DOM.

## Deliberate non-goals (and why)

- **No ESLint config.** TypeScript strict mode with `noUnusedLocals` /
  `noUnusedParameters` catches the same class of everyday mistakes. Adding ESLint would
  mean four more devDependencies and a config file to keep in sync, for marginal gain
  in a codebase this size. `tsc --noEmit` is the lint gate; `npm run build` runs it.
- **No route-based code splitting.** The whole app is one ~115KB gzipped JS chunk.
  For this build's size that's a non-issue and simpler to reason about; `React.lazy`
  per route is the obvious next step once the number of routes grows meaningfully.
- **No inline text highlighting of claims inside the document prose.** This was
  attempted and deliberately reverted: claims are authored as clean, standalone
  assertions rather than verbatim extracts (realistic — real claims are usually
  *summarized* from source text, not quoted), so naive substring matching against the
  section body would highlight some claims and silently miss most others. A
  half-working highlight would look like a bug. Instead, each section shows its claims
  as a clearly separated, always-reliable list of chips directly below the prose.
- **No real persistence layer.** The store is in-memory by design — this is a frontend
  product demo, and a real backend is explicitly out of scope per the brief. `DEMO_NOW`
  keeps the demo deterministic in its place.
