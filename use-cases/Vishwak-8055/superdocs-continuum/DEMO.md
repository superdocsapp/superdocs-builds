# Demo

## Setup

For a local browser screenshot/demo on Windows, double-click `preview.cmd`.
It starts a local server and opens the preview at
`http://localhost:4173/preview/`. The browser harness loads only the shipped
JSX artifact plus its React runtime modules; the application itself makes no
API calls or login requests.

For the target single-file runtime, open `dist/document_os.jsx` as an
interactive artifact.

## Walkthrough

1. **Document tab** — Northstar Customer Agreement. §4.2 has an
   "Obligation" badge — click it to open the inspector (source, evidence,
   confidence).
2. **Consequences tab** — **"What does this affect?"** shows the real
   consequence closure of the current canonical state: direct, indirect,
   and potential/context-only items, each with a clickable "why" path back
   to the source, plus the two conflict relationships that touch this
   obligation (reported separately from impact). Try an invalid value
   first — blank, negative, `12.5` — to see real validation before
   proposing a real one.

### Scenario A — safe change (input: 30 -> 60)

3. Propose **60** -> **Simulate change**. This builds a candidate world
   independent of canonical, computes consequences against it, and shows:
   - **Analysis** — direct/indirect/potential consequences with why-paths.
   - **Forecast** — the pre-existing Sales Terms conflict (45 days) stays
     *open* (60 doesn't match it); nothing is newly introduced.
   - **Diff** — a real text diff (Customer Agreement + Invoice Template)
     and semantic diff, both derived from comparing the two worlds.
4. **Approve & apply** -> verification runs six checks against the
   candidate, all pass, including "documents outside the change scope are
   untouched" (Sales Terms, Renewal Policy, Pricing Policy, Enterprise
   Terms Addendum, checked byte-for-byte). The candidate becomes canonical
   in one update.
5. **Document tab** — §4.2 now reads "sixty (60) days." Check the
   **Evidence tab** -> Invoice Template's source link — its preview also
   reads sixty days, not stuck at the original value.
6. **History tab** — the scenario is logged with the documents it actually
   changed and the number of checks run.

### Scenario B — a conflict resolved by the proposal itself (input: 30 -> 45)

7. Back in Consequences, propose exactly **45**. The forecast now reports
   the Sales Terms conflict as *resolved* — a real comparison against its
   own declared value — then **Reject** it and confirm on the Document tab
   that nothing changed (rejection never reaches verification or commit at
   all; the state machine has no path from REJECTED into APPROVED).

### Scenario C — unsafe change, verification blocks it (input: 30 -> 120)

8. Propose **120**. The Enterprise Terms Addendum caps the Payment Term at
   90 days; 120 crosses it while 60 did not (90 itself would still pass —
   the cap is inclusive), so the forecast reports a **newly introduced**
   conflict, distinct from the pre-existing one.
9. **Approve & apply** anyway. Verification's "no new conflicts" check
   genuinely fails. `commitWorld` returns nothing to commit and the
   version does not advance — the scenario reaches ROLLED_BACK, not
   COMMITTED. The Document tab still reads sixty days from Scenario A;
   nothing from this attempt was written. The attempt is still logged in
   History, marked rolled back.

10. **Graph tab** — hover any node for the path highlight. **Intelligence
    tab** — health score with all five dimensions computed from the
    corpus, plus a real entity and object count.

## What each scenario actually demonstrates

- **A** — a full commit: candidate creation, consequence and diff
  generation, a clean forecast, verification passing on all six checks,
  and a canonical-world replacement, all backed by the corresponding
  functions in `src/engine.js`.
- **B** — that resolving a conflict and rejecting a scenario are both real,
  distinct paths, neither of which touches canonical state.
- **C** — that a verification failure genuinely blocks a commit: the same
  code path as A runs, produces a failing check, and `commitWorld` returns
  `committed: false` with the version unchanged — this is not a separate,
  scripted "failure" screen.
