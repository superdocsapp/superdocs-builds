# TASK.md — Amendment and Q&A Delta Applier

## Assigned build

- **Who it serves:** GovCon proposal manager, mid-bid, when the agency changes the rules.
- **What it does:** Feed it an amendment or the agency's published Q&A. It diffs against the original solicitation, identifies affected proposal sections (page limits, due dates, evaluation weightings, new/deleted requirements) including second-order effects, and stages the required edits against the in-flight proposal — each edit annotated with the amendment paragraph that drove it. Produces an amendment-response log for the compliance file.
- **Strong = :** affected-section mapping is correct including second-order effects; every edit traces to an amendment paragraph; untouched sections are provably untouched.
- **Difficulty:** S3
- **Surfaces:** Multi-document, search, Review, chat, export
- **Deliverable location:** PR into `github.com/superdocsapp/superdocs-builds`, under `use-cases/monisha/amendment-qna-delta-applier/`

## Minimum API contract (build against this first)

Four SuperDocs calls: **upload → chat (edit instruction) → approve → export**. REST or MCP; assigned card leans REST but MCP substitution is explicitly allowed.

## Known gotchas from the brief

- Proposed-change content in the API response is a **JSON-encoded string** — needs a second `JSON.parse` / `json.loads`. Skipping it is the #1 cause of "empty diff card / everything undefined."
- Large-document ops or deep model settings can take 30s–several minutes with **no visible progress** — that's normal, not a crash. Poll, don't assume failure.
- Exports/downloads never cost operations — save/export often. Searches do cost operations.
- Give any loop/measurement a small-sample mode + explicit stopping rule to avoid burning the operation quota.

## Working conventions

Same as `task1-agentic-system/TASK.md`: log assumptions in PROGRESS.md, checkpoint long work, no secrets in git, tests runnable without a live key where possible (mock the SuperDocs API boundary for unit tests; keep a small number of real integration tests behind an env flag).
