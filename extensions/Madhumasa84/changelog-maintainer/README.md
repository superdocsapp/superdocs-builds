# SuperDocs public changelog maintainer

An offline-first optional extension for maintaining one canonical, append-only Markdown changelog. It implements the page-301 open-list brief: preview a targeted release update, require item-level human decisions, append only approved bytes, derive verified PDF/DOCX artifacts, and prepare a publication plan without publishing.

This is a separate project from `sdx` and the Release Readiness Analyst. It reuses their proven behavioral ideas locally; it does not import either project or modify them. The default workflow makes zero SuperDocs API calls, uses no credentials, and never calls GitHub. Verified live/API/billable operations performed: 0. Release classification is supplied by structured JSON; no external LLM or MCP server is invoked.

## Commands

```bash
# Build, type/syntax check, lint, and tests
npm run build
npm run typecheck
npm run lint
npm test
npm run security-scan
npm ci

# Create a no-spend preview. State is written under --state-dir.
node src/cli.js preview \
  --changelog fixtures/changelog.md \
  --release fixtures/releases/release-01.json \
  --state-dir /tmp/changelog-state \
  --json

# Submit every item explicitly. Nothing is implicit.
node src/cli.js approve --run <run-id> \
  --state-dir /tmp/changelog-state \
  --accept change_2026.01_preview \
  --reject change_2026.01_hashes \
  --output-dir /tmp/changelog-artifacts \
  --json

# Recover a persisted run without creating a replacement update.
node src/cli.js resume --run <run-id> --state-dir /tmp/changelog-state --json

# Prepare, but do not perform, publication actions.
node src/cli.js publish-dry-run --run <run-id> \
  --state-dir /tmp/changelog-state --output /tmp/publication-plan.json
```

`preview` is always no-spend. `approve` requires an explicit decision for every proposed item; a partial decision set remains pending with exit status 3. A rejected item stays in the durable audit manifest and is not appended.

## Guarantees

- Markdown is the canonical source of truth.
- Historical bytes are never normalized. The pre-update SHA-256 is checked again while holding the canonical-file lock before append.
- Approved bytes are generated before approval and bound to a candidate-block hash. Stale or tampered approval cannot authorize different content.
- Canonical and state writes use temporary files plus atomic rename. State and lock files use restrictive permissions.
- A run checkpoints after preview, decisions, append, and export. `resume` recovers an interrupted run without creating a replacement release.
- One changelog is serialized by an inter-process lock; different changelogs can proceed concurrently.
- Generated input metadata and derived output origin metadata prevent self-trigger loops.
- PDF and DOCX are derived offline fixtures and are structurally validated. They are not live SuperDocs proof.
- The stopping rule defaults to ten sequential releases and requires an explicit no-spend preview.

## Open-list alignment

Page 301 describes an S2 build for an open-source maintainer or devrel owner. The required route is a pull request into the public repository's extensions folder. This project only prepares a local dry-run plan; it does not create a PR, publish, upload, or contact anyone. The package is intentionally private and is not published to npm.

See `DESIGN.md`, `THREAT-MODEL.md`, `docs/requirements-matrix.md`, and `docs/demo.md` for boundaries and evidence.
