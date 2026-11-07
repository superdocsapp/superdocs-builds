# Extra-credit evidence capture

## Required screenshots

These files are stored under `evidence/screenshots/`:

- [x] `01-initial-review-state.jpg` — three-pane workspace with the first change selected.
- [x] `02-claimed-vs-actual-mismatch.png` — mismatch inspector with agent claim and artifact check.
- [x] `03-independent-revert.png` — one change reverted without disturbing another approved change.
- [x] `04-completed-human-review.png` — queue after every proposed change received a human decision.
- [x] `05-build-and-tests.jpg` — clean install, build, and tests.

Machine-readable exports live under `evidence/exports/`.

## Required command evidence

```powershell
npm ci
npm run build
npm test
```

## Optional 30–45 second extra-credit clip

1. Open workspace.
2. Select the renewal-notice change → Approve.
3. Revert that applied change and confirm sibling states stay put.
4. Select unrelated payment change → show mismatch → Reject.
5. Select false claim → show no artifact change.
6. Export evidence.

## Form-ready description (only after the evidence above exists)

> Extra credit — SuperDocs Agent Review Workspace. I built the Open Task List's coding-agent document review surface as a VS Code panel: before/after changes grouped by agent turn, explicit approve/reject/revert decisions, independent review state, a claimed-vs-actual verifier that catches an agent reporting an edit that did not happen, support for more than one agent client through one neutral model, and evidence/DOCX export. I used deterministic synthetic documents for repeatable review states and kept the integration boundary explicit rather than claiming fixture activity was live MCP traffic.
