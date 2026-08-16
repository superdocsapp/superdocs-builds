# Jupyter Notebook to Paper

SuperDocs Task 2.2 prototype. This TypeScript application consumes an already-executed Jupyter notebook, extracts grounded evidence, and generates a structured paper preview with incremental updates and human review.

## What is implemented

- Executed `.ipynb` parsing.
- Metric, statistic, figure, equation, and source-range extraction.
- Markdown-derived titles and preserved notebook prose.
- Conflict detection for contradictory metrics.
- Markdown and HTML paper rendering.
- Incremental evidence diffing and affected-block regeneration.
- SuperDocs synchronous and asynchronous chat, job polling, item-level approval, and export.
- Review UI with approve/reject decisions per paper block.
- Visible parse/evidence/claims/paper/review/commit stages.
- Retry, skip, and escalation decisions.
- Checkpoint/resume behavior, run IDs, locking, and stale-lock recovery.
- MCP server integration.
- Prompt-injection safety checks and persistent SuperDocs usage telemetry.

Notebook execution is intentionally outside this prototype: provide an executed notebook with outputs already present.

## Requirements

- Node.js 18 or newer; Node.js 20 LTS is recommended.
- npm.
- An executed Jupyter notebook for local generation.
- A SuperDocs API key only for live SuperDocs calls.

## Download and verify from GitHub

After the project is published, either download the repository ZIP and extract it, or clone it:

```powershell
git clone https://github.com/superdocsapp/superdocs-builds.git
cd superdocs-builds/extensions/Purujeet-git/jupyter-notebook-to-paper
npm install
npm run verify
```

`npm run verify` runs the TypeScript build and the complete test suite. The expected result is 10 test files and 24 passing tests.

Do not commit `.env`, API keys, generated state, or usage ledgers. These paths are ignored by `.gitignore`.

## Local setup

```powershell
npm install
npm run build
npm test
```

Copy `.env.example` to `.env` only when using live SuperDocs calls:

```text
SUPERDOCS_API_KEY=your-key
SUPERDOCS_BASE_URL=https://api.superdocs.app
```

## Generate a paper

```powershell
npm run dev -- parse examples/synthetic_research.ipynb
npm run dev -- generate examples/synthetic_research.ipynb
```

The generator writes `generated-paper.md` and `state-v1.json` beside the notebook.

## Test a two-version incremental update

The strongest local proof is the end-to-end test:

```powershell
npm test -- --run tests/incremental-e2e.test.ts
```

It creates two actual notebook versions at one stable path, changes one metric, verifies exactly one evidence item changes, and verifies all unaffected paper blocks remain identical.

For a manual run:

```powershell
npm run dev -- snapshot <notebook.ipynb> <state-v1.json>
npm run dev -- update <notebook.ipynb> <state-v1.json> <state-v2.json>
npm run dev -- diff <state-v1.json> <state-v2.json>
```

The update output identifies `changes` and `affectedBlockIds`. The generated Markdown is rewritten using the merged paper.

## Review workflow

Run the staged pipeline:

```powershell
npm run dev -- run examples/synthetic_research.ipynb demo/state.json demo/run.json
```

The normal run stops at a review gate and creates `demo/state.json.draft.json`. Start the browser review UI:

```powershell
npm run dev -- review demo/state.json.draft.json 4173
```

Open `http://127.0.0.1:4173`, approve or reject every block, then commit:

```powershell
npm run dev -- review-commit demo/run.json
```

For a trusted noninteractive run, use `auto` as the fourth argument to `run`. Resume a checkpoint with `resume`.

## SuperDocs integration

The active SuperDocs API accepts the generated HTML in `document_html`; it does not require a separate upload endpoint. The supported flow is HTML in, proposed changes and updated HTML out:

```powershell
npm run dev -- superdocs-chat <notebook.ipynb> "Improve the results section"
npm run dev -- superdocs-async-chat <notebook.ipynb> "Rewrite the first Results paragraph" demo-session
npm run dev -- superdocs-job <job-id> 120000
npm run dev -- superdocs-approve <session-id> <job-id> true
npm run dev -- superdocs-export <document.html> <output.docx> docx
```

The async command returns a `job_id`. Poll until pending changes or completion, approve changes item by item, and then export. The API key is read server-side from `.env` and is never printed.

## MCP server

```powershell
npm run mcp
```

The stdio MCP server exposes notebook parsing, paper preview, state inspection, review, commit, and HTML export tools.

## Usage telemetry

SuperDocs provider-reported usage is stored in `superdocs-usage.json` by default:

```powershell
npm run dev -- telemetry
```

The ledger records quota, billable status, operations charged, tier, session/job identifiers, and timestamps. A currency cost is not invented when the provider does not return one.

## Jupyter screenshot workflow

From a Jupyter notebook, use Python `subprocess.run` with `npm.cmd` and this repository as `cwd` to run `snapshot`, `update`, and `diff`. Display `generated-paper.md` with `IPython.display.Markdown`. Capture the original paper, the update output showing one affected block, the updated paper, and the passing `npm test` output.

## Repository scope and remaining external deliverables

This repository implements the Jupyter notebook-to-paper Task 2.2 build. It does not contain the separate Google Sheets roster-to-documents application, the general mixed-format Task 1 platform, the Task 3 use-case research, or the Task 4 demo video/submission form.

The public `extensions` pull request is a release/submission step and requires the correct target repository and branch.
