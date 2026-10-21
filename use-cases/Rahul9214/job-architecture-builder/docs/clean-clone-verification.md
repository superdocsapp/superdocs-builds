# Clean-clone verification

## Source

- Branch: `task2-job-architecture-builder`
- Commit: `274866eda8d266221853e79bff6862bfe653a9fc`
- Clone destination: `%TEMP%\job-arch-clean-clone` (`C:\Users\LENOVO\AppData\Local\Temp\job-arch-clean-clone`)
- Log: `%TEMP%\job-arch-clean-clone.log`
- Method: `git clone --branch task2-job-architecture-builder --single-branch D:\superdocs-builds <dest>`
- Did not copy `.venv`, `node_modules`, `.runtime`, `artifacts`, `exports`, or `web/dist` from the working tree.

Phase 9 documentation, screenshots, and the `.chip.warn` CSS contrast fix were **uncommitted** at clone time, so the clone exercised HEAD README and HEAD product code.

## Commands (from the use-case directory inside the clone)

```text
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m compileall src tests
cd web
npm ci
npm run lint
npm run typecheck
npm test
npm run build
```

Then, with `JOB_ARCH_PORT=8011`:

```text
.\.venv\Scripts\python.exe -m job_architecture.web
```

```text
GET http://127.0.0.1:8011/api/health
GET http://127.0.0.1:8011/
GET http://127.0.0.1:8011/architecture
```

No `SUPERDOCS_API_KEY` was set.

## Results

| Step | Result |
| --- | --- |
| clone | HEAD `274866eda8d266221853e79bff6862bfe653a9fc` |
| venv + pip install -e ".[dev]" | ok |
| pytest | **234 passed, 1 skipped** (SPA fallback skipped because `web/dist` did not exist yet — expected for this command order) |
| compileall | ok |
| npm ci | ok |
| lint | ok |
| typecheck | ok |
| npm test | **12 passed** |
| npm run build | ok |
| GET /api/health | 200 `{"ok":true,"service":"job-architecture-reviewer"}` |
| GET / | 200 HTML, title Job architecture reviewer |
| GET /architecture | 200 HTML, same SPA index (hard GET, not 404) |

## Failures and fixes

None. README install commands at this commit were sufficient. No manual patching of the clone.

The skipped pytest is `test_spa_fallback_serves_index_when_built`. After `npm run build`, the production GETs proved the SPA fallback.

## Working-tree note

Uncommitted Phase 9 files (this document, assignment audit, screenshots, README rewrite, warn-chip CSS) are not in the clone. Re-run after they are committed if reviewers clone the branch later.
