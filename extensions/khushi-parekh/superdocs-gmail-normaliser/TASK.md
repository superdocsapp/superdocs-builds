# TASK.md

How to work with this repo (the task doc's own suggested convention).

## What this is
Gmail add-on: inbound attachment normaliser. Assigned build for the SuperDocs
Round 2 engineering/growth task. Difficulty band **S2**.

## Scope (from the assignment card)
- **Who it serves:** a coordinator receiving documents from many outside
  parties, in whatever format they have.
- **What to build:** open a message with an attachment, offer to normalise
  it into the org's house template (headings mapped, tables restyled, logo
  placed, cover page added). Handle the awkward cases (legacy .doc,
  OpenDocument, RTF, scanned PDF) rather than refusing them.
- **Surfaces touched:** API, templates, export, chat.
- **Where it goes:** a pull request into the public `superdocs-builds`
  repository, `extensions/` folder.

## The four-call contract (non-negotiable floor)
upload -> chat (edit instruction) -> approve -> export. Everything else on
the surface is optional depth. This build sticks close to the floor and
spends its effort on making that pipeline honest and resumable-in-spirit
rather than on extra surface area.

## Working conventions
- Assumptions get logged in `PROGRESS.md`, not silently baked into code.
- Secrets never get committed - API key lives in Apps Script Script
  Properties (see `Config.gs` -> `setup()`), and `.clasp.json` (which holds
  a project-specific script ID) is git-ignored.
- Tests that don't need a live key or the Apps Script runtime live in
  `test/` and run with `node --test` (zero installs).
