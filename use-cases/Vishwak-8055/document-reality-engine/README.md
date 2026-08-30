# SuperDocs â€” Document Reality Engine

> A document is not a file. It's a claim graph: text that asserts things, evidence that
> backs (or fails to back) those assertions, rules the document must satisfy, and a
> history of everything that changed. SuperDocs renders that graph and puts a reviewer
> in control of it.

This is a from-scratch, self-contained reference build of the SuperDocs Document
Reality Engine: a single flagship document (a messy, mid-negotiation vendor contract)
and five supporting documents, modeled with real claims, evidence, requirements, risks,
changes, reviews, and an audit trail â€” plus the product experience for working with all
of it.

---

## 1â€“3. What this is, why it exists, and the problem

A traditional document system answers **"where is the document?"** â€” storage, versions,
permissions. That's necessary and not remotely sufficient. The moment a document
actually matters â€” a vendor contract, a security questionnaire, a policy, a compliance
letter â€” the real questions are harder:

- What does this document **claim**, specifically?
- What **evidence**, if any, backs each claim â€” and is that evidence still current?
- What **rules** is this document supposed to satisfy, and which ones does it fail, and *why*?
- What is the document's **risk**, in terms a reviewer can act on instead of a bare score?
- What actually **changed** between versions, at the level of claims and risk â€” not a line diff?
- Who **decided** what, when, and what's still open?

Answering these by hand, per document, is why compliance, legal, and risk teams drown in
review queues. SuperDocs' thesis is that a document's *trustworthiness* is itself
structured data â€” extractable, computable, and explainable â€” and that a product built
around that structure can carry far more of the review burden than a system that only
stores bytes.

## 4. Product thesis

**Document â†’ Structure â†’ Claims â†’ Evidence â†’ Rules â†’ Verification â†’ Risk â†’ Changes â†’
Decisions â†’ Actions â†’ Audit Trail.**

Every screen in this build exists to make one link in that chain visible and actionable.
The hero experience â€” a document's **Reality** tab â€” is the whole chain summarized in
one view, with a path into each link.

## 5â€“6. Core architecture & domain model

```
UI (React components, one concern per file)
 â†“ reads/writes
Application State (Zustand store â€” documents + cross-cutting UI state)
 â†“ built from
Domain Model (src/types/domain.ts â€” Document, Section, Claim, Evidence,
              Requirement, Risk, Decision, Action, ChangeEvent, ReviewEvent, Provenance)
 â†“ scored by
Domain Logic (src/domain/* â€” pure functions: compliance %, risk score, claim
              confidence, staleness, change summaries, search, dashboard aggregation)
 â†“ designed to be produced by
Intelligence Services (src/services/intelligence â€” typed interfaces + a
                        deterministic mock implementation standing in for a real model)
 â†“ every state change appends to
Audit Trail (ReviewEvent[] â€” provenance and accountability, not a side effect)
```

The full write-up, including the tradeoffs, lives in **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

The domain model (`src/types/domain.ts`) is intentionally a plain, serializable data
shape with **no derived fields baked in**. `confidence`, `complianceScore`, and
`riskLevel` are never stored â€” they're computed on demand from the underlying facts by
`src/domain/*`, so the "why" behind every number is always one function call away, and
the model is ready to be filled by a real extraction/verification backend instead of
hand-authored fixtures.

## 7. Major workflows

- **Open a document â†’ read its Reality** â€” confidence, compliance, evidence coverage,
  risk level, and why, all in one screen (`/documents/:id`).
- **Trace a claim** â€” select any claim and follow **Claim â†’ Evidence â†’ Source â†’
  Verification** in the Provenance Thread; missing links render as visibly broken,
  not silently absent (`/documents/:id/claims`).
- **Understand compliance** â€” every requirement's pass/warn/fail comes with a stated
  reason, grouped by category (`/documents/:id/requirements`).
- **Understand risk** â€” an explainable, weighted risk score broken into factors, plus
  live recommended actions from the (mock) intelligence layer (`/documents/:id/risk`).
- **Understand a change** â€” "what actually changed" between versions, above the level
  of a line diff (`/documents/:id/changes`).
- **Review and decide** â€” approve, request changes, assign and complete actions, and
  comment, with every action logged to the audit trail (`/documents/:id/reviews`).
- **Reconstruct history** â€” the full chronological event log for a document
  (`/documents/:id/timeline`).
- **Work across documents** â€” a dashboard that answers "what needs my attention,"
  plus cross-document Reviews, Risk Register, and Audit views, and a âŒ˜K command
  palette with both free-text search and canned commands ("Show high-risk documents",
  "Find unsupported claims", â€¦).

## 8. Screens / features

| Area | Route | What it's for |
|---|---|---|
| Dashboard | `/` | Workspace-wide "what needs my attention" + metrics |
| Documents | `/documents` | Searchable, filterable document grid |
| Document Reality | `/documents/:id` | The hero â€” confidence, compliance, risk, actions, latest change |
| Claims & Evidence | `/documents/:id/claims` | Reading pane + claims list + Provenance Thread drawer |
| Requirements | `/documents/:id/requirements` | Compliance breakdown, grouped, each with a stated reason |
| Risk | `/documents/:id/risk` | Explainable risk factors, live recommendations, resolvable findings |
| Changes | `/documents/:id/changes` | Version-over-version change intelligence |
| Reviews | `/documents/:id/reviews` | Approve / request changes, decisions, actions, comments |
| Timeline | `/documents/:id/timeline` | Full audit trail |
| Reviews (global) | `/reviews` | Cross-document review queue |
| Risk Register | `/risks` | Cross-document, filterable risk list |
| Audit | `/audit` | Cross-document, filterable event log |
| Command Center | `/command-center` | Full-page search + canned commands |

The information architecture deliberately differs from a flat 10-item nav: Evidence,
Requirements, Changes, Decisions, and Actions are richest **in the context of a specific
document**, so they live as tabs on the Document Reality page instead of ten shallow
top-level pages. Reviews, Risk, and Audit get dedicated global pages because those are
genuinely useful rolled up across the whole workspace. (See ARCHITECTURE.md for the
reasoning in full.)

## 9. Technical architecture

- **React 19 + TypeScript (strict)**, built with **Vite**.
- **Tailwind CSS v4** (CSS-first config, custom design tokens in `src/index.css`) for styling.
- **Zustand** for the cross-cutting application store (documents + toasts + command
  palette state); page-local UI state (filters, sort, form drafts) stays in the
  component that owns it.
- **React Router v7** (declarative mode) for routing, including deep-linkable tab and
  entity state via path segments and query params.
- **Vitest + React Testing Library** for tests.
- No state-management or UI-kit dependency beyond what's listed in `package.json` â€”
  deliberately kept small enough that another engineer can read all of it.

## 10. AI extension points

`src/services/intelligence/types.ts` defines eight interfaces â€” claim extraction,
evidence retrieval, contradiction detection, requirement extraction, document
classification, risk analysis, change-impact analysis, and review recommendations.
`src/services/intelligence/mock/mockIntelligenceServices.ts` implements all eight with
deterministic, dependency-free logic (regex-based extraction, keyword scoring, the same
risk engine used everywhere else) â€” good enough to be genuinely useful in the demo, and
structured so a real model-backed implementation can replace the mock without touching
any UI code. The Risk tab's "Recommended actions" panel is powered by this layer live,
via an `async` call, so the seam is exercised, not just declared.

## 11. Trust / provenance model

> Don't just trust the document. Understand why it can be trusted.

Every claim can be traced: **Claim â†’ Evidence â†’ Source â†’ Verification Event.** The
`ProvenanceThread` component (used in the claim detail drawer) renders that chain
literally â€” and when a link is missing (no evidence attached, no named source, never
verified), the chain visibly **breaks**: a hollow, dashed node instead of a silently
omitted step. The same solid/hollow grammar is used for every claim and requirement
indicator in the product, so "this hasn't been evaluated yet" always looks the same,
everywhere.

Evidence staleness is a computed rule, not a flag someone set: certifications, audit
reports, and attestations are treated as stale after 12 months with no renewal on file,
or immediately once an explicit `expiresAt` has passed â€” see `src/domain/evidence.ts`.

## 12. Testing

```
src/test/domain/*        pure-function tests: compliance, risk, claims, evidence,
                          changes, search, dashboard aggregation (against both
                          synthetic fixtures and the real seed documents)
src/test/store/*         reviewer actions: state updates + audit-trail side effects
src/test/components/*    React Testing Library: Dashboard, Document Detail
                          (tab switching, claim drawer, verify, resolve risk,
                          approve/request-changes), Command Palette
```

Run them:

```bash
npm test          # vitest run â€” used in CI / this repo's release gate
npm run test:watch
```

## 13â€“14. Local setup & build

Requires Node 20+.

```bash
npm install
npm run dev        # http://localhost:5173
npm test           # run the test suite
npm run build      # tsc --noEmit + production build â†’ dist/
npm run preview    # serve the production build locally
```

## 15. Design decisions worth calling out

- **Derived numbers are never stored.** Confidence, compliance %, and risk level are
  always computed from underlying facts (see Â§6). This was worth the extra function
  calls: it's the difference between a dashboard that can explain itself and one that
  can't.
- **A fixed demo clock (`DEMO_NOW`).** Staleness and "recently changed" are computed
  against a constant, not `Date.now()`, so the workspace's risk posture doesn't quietly
  drift as time passes. A production build swaps this for the real clock.
- **Compliance is `satisfied / total`, not partial credit for warnings.** Simpler to
  explain, and it doesn't let three warnings quietly launder into an inflated score.
- **A reviewer can override computed evidence staleness** (`reviewerOverride` on
  `Evidence`) â€” the "mark evidence stale" action is a real, persisted judgment call,
  not just a re-run of the date math.
- **One IBM Plex type superfamily, three roles**: Serif for the document's own words
  (the reading pane), Sans for the product's voice, Mono for the system's voice
  (ids, timestamps, scores). See ARCHITECTURE.md for the full visual-design rationale.
- **TypeScript strict mode is the lint gate**, not a separate ESLint config â€” `noUnusedLocals`
  / `noUnusedParameters` catch the same class of issues ESLint's core rules would, with
  one less devDependency and one less config file to keep in sync.

## 16. Future production architecture

The most obvious next steps, in the order they'd matter:

1. **Real intelligence backend.** Swap `mockIntelligenceServices` for implementations
   backed by an actual extraction/verification model; the interfaces don't change.
2. **Persistence.** The store is in-memory; a production version needs a real backend,
   optimistic updates, and conflict handling for concurrent reviewers.
3. **Auth & multi-tenancy.** `CURRENT_USER` is a constant; real auth, roles (who can
   approve vs. comment), and per-workspace document scoping come next.
4. **Real document ingestion.** Sections/claims are hand-authored here; a production
   pipeline needs OCR/parsing for uploaded files feeding `claimExtraction` and
   `requirementExtraction`.
5. **Route-based code splitting.** The bundle is a single ~115KB gzipped chunk today,
   fine for this build; `React.lazy` per route is the natural next optimization once
   the surface area grows.

---

### Why this matters to SuperDocs

The founder-level bet here is that **verification is the product**, not a feature
bolted onto document storage. Every design decision in this build â€” derived-not-stored
scores, a visible provenance chain, an audit trail that's a side effect of every action
rather than a separate logging pass, a risk score that comes with its own explanation â€”
is in service of one sentence: *a reviewer should never have to take SuperDocs' word for
it.* That's the difference between "AI for documents" (a commodity category) and a
document operating system a compliance team actually trusts to carry risk they're
accountable for.

---

## Project structure

```
src/
  types/domain.ts            the entire domain model, one file
  data/                      seed documents (1 flagship + 5 supporting) + shared constants
  domain/                    pure functions: compliance, risk, claims, evidence,
                             changes, provenance, search, attention, utils
  services/intelligence/     AI-ready interfaces + deterministic mock implementation
  store/appStore.ts          Zustand store: documents + reviewer actions + toasts
  components/
    layout/                  AppShell, Sidebar, NotFoundPage
    ui/                      design-system primitives (Badge, Tabs, Drawer, Modal, â€¦)
    dashboard/ documents/ document-detail/ reviews/ risks/ audit/ command-center/
  test/                      domain, store, and component tests
```

## Credits

Built and engineered by **Vishwak**.
