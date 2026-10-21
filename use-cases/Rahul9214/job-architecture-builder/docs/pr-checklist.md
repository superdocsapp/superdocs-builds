# PR checklist

Do **not** open the PR from this document. Fill it when committing and pushing later.

## Required

- [x] Project folder is `use-cases/Rahul9214/job-architecture-builder/`
- [x] No files outside that folder were modified for this work
- [x] README is the reviewer entry point
- [x] Screenshots present under `screenshots/` (overview, architecture, title-evidence-conflict, exceptions, framework, profile, change-impact, review, export, collapsed-sidebar, mobile-overview)
- [x] Working-tree tests green after this RC pass (pytest 250; vitest 13; lint/typecheck/build green)
- [x] Clean-clone of `274866eda8d266221853e79bff6862bfe653a9fc` green (`docs/clean-clone-verification.md`)
- [x] Secret scan recorded (`docs/security-check.md`)
- [x] Live SuperDocs evidence recorded (`docs/live-verification.md`)
- [x] Task 2 audit complete (`docs/assignment-audit.md`) including A–AO map
- [x] No secrets in tracked files
- [x] `.env`, `.runtime/`, `exports/`, `artifacts/`, `.venv/`, `node_modules/`, `web/dist/` not tracked
- [ ] Branch pushed / up to date with remote (human)
- [ ] Commit history coherent after RC files are committed (human)
- [ ] PR not opened yet (by request)

## Suggested PR

**Title:** `feat: add job architecture and levelling framework builder`

**Body:**

```text
## Summary

- Local FastAPI + React reviewer workspace that builds families, tracks, levels, competency matrices, and role profiles from synthetic JDs.
- Evidence-first classification (titles never assign family/track/level), honest provisional/misfit handling, and surgical canonical-level updates with a human gate.
- SuperDocs surfaces (multi-document, templates, search, review, export) are proven on the live CLI; the web app stays fully usable offline and writes local DOCX only.

## SuperDocs

Upload (multi-document session), templates, reviewed async edits, approve/reject, Search (async cross-session search), and export. Live CLI is optional. Framework export attempts 1–2 returned a source JD and are retained; attempt 3 HTML + session_id semantic PASS. Profile DOCX and Search resume are verified. See docs/live-verification.md.

## Evidence-based architecture

Family, track, and level come from JD evidence. Titles are excluded from clustering. Typed title_conflict metadata flags seniority/management/scope mismatches without changing the evidence-based assignment.

## Honest exceptions

Sparse, hybrid, and outside-architecture roles remain provisional or misfit. The UI does not auto-assign them.

## Surgical propagation

Canonical level edits identify dependent profiles via explicit edges and patch only the corresponding level-expectation fields. Unrelated sections are hash-checked. Rejected attempts remain unapplied.

## Testing

- Offline pytest (domain, SuperDocs fake, live orchestration fake, web API)
- Vitest (mocked fetch, including collapsed-nav tooltip and export combobox)
- Production `npm run build` served by FastAPI
- Clean-clone of 274866e followed README without a SuperDocs key

## Screenshots

See screenshots/ and README (overview, title-vs-evidence, change impact prominently).

## Limitations

Lexical/TF-IDF reasoning, in-memory web store, no HRIS/auth, no hosted deploy, live SuperDocs requires the reviewer’s key. Web live export is intentionally disabled.

## Test plan

- [ ] Fresh clone, no SUPERDOCS_API_KEY: venv, pytest, npm ci, lint, typecheck, test, build
- [ ] python -m job_architecture.web → http://localhost:8000 (or JOB_ARCH_PORT)
- [ ] GET /api/health, /, /architecture, /impact
- [ ] Analyze Corpus A and Corpus B
- [ ] Architecture title-vs-evidence + Open evidence
- [ ] Exceptions misfit reads as an architecture finding
- [ ] Framework IC1–IC5 / M1–M3
- [ ] Collapse sidebar: hover and keyboard tooltips, no clip
- [ ] Export profile combobox keyboard + mobile widths 320–430
- [ ] Impact OLD/NEW → Review approve/reject
- [ ] Local DOCX export; live SuperDocs button remains disabled with adjacent reason
```
