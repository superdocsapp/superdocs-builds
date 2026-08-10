# PROGRESS.md — assumptions, calls made, and things found

A running log. Newest entries at the bottom of each section. The brief asked for logged assumptions
rather than blocked questions, so anything ambiguous gets resolved here and the reasoning recorded.

---

## Assumptions and calls made

### 2026-08-10 — Scope: Markdown and MDX only, DOCX out of scope

The assigned card says "documents in a repository" and names both DevTools and Marketing ops, which
implies `.docx` collateral as well as `.md`. Committed to Markdown/MDX only.

Reasoning: the card's own definition of strong includes "findings map to precise locations" and
"`--fix` never applies anything without approval". Both are honest in Markdown — character offsets
are real, git diffs are reviewable, and a rejected finding can be proven byte-identical afterwards.
In a binary DOCX committed to git, "precise location" and "nothing else changed" are much harder to
*prove*, and an unproven claim is worse than a declared limitation. SuperDocs accepts `.docx` on the
same endpoints, so the format is a config change rather than a rewrite if this is revisited.

### 2026-08-10 — Engine: hybrid, not model-only

Mechanical rules (banned terms, heading case, fence languages) run locally and deterministically.
Only judgment — tone, voice, structure, prose against the style guide — goes to SuperDocs.

Reasoning: a rule that should never vary should never be non-deterministic, and it should not cost
an operation. The card also asks for "configurable severity per rule", which implies stable rule
identities that a team can pin severities to; model-invented rule names would not be stable. The
brief explicitly blesses this shape: deliberate hard-coded defenses alongside intelligent logic are
a legitimate fix, not a patch.

### 2026-08-10 — Folder is `extensions/ayush-3516/`, not `extensions/ayush-chaudhari/`

`CONTRIBUTING.md` in this repository specifies `extensions/<your-github-username>/<project-name>/`.
The GitHub username is `ayush-3516`. Planning notes had guessed the personal-name form; the
repository's own instructions win.

### 2026-08-10 — Build tooling: stdlib `venv` + `pip`, not `uv`

`uv` is not installed on the build machine. `pyproject.toml` is plain PEP 621 with a hatchling
backend, so `uv` works for anyone who has it and `pip install -e '.[dev]'` works for anyone who does
not. No project-level dependency on a tool a stranger might not have — the card asks that a stranger
can go from clone to working in minutes.

### 2026-08-10 — The human gate uses SuperDocs' own HITL API rather than a local imitation

`POST /v1/chat/{session_id}/approve` accepts per-item `{change_id, approved}` decisions natively,
and async jobs pause at `awaiting_approval` with proposals in `metadata.pending_changes`. So
"approve what is right and reject what is wrong in the same review, item by item" is satisfied by
using the product as designed rather than by tracking approvals locally and replaying them.

Consequence for the design: the local review UI is a thin client over that API, and it is built
*after* the machine-drivable path (`--plan` / `apply` with a `decisions.json`), not before. The gate
therefore works headlessly and stays testable without a browser.

---

## Cuts made, and why

*(Nothing cut yet. Recorded here as it happens, for the Task 4 write-up.)*

---

## Bugs, rough edges and confusing moments in SuperDocs

*(Collected from day one for the submission form's first question. Reported to hello@superdocs.app
and via the in-app bug button as they are found.)*

### 2026-08-10 — Documentation: upload and export endpoints publish an empty response schema

`POST /v1/documents/upload-base64` and `POST /v1/documents/export` both document their 200 response
as `{}` in the OpenAPI spec at `docs.superdocs.app/openapi.json`. The prose describes what comes
back (`chunks_count`, `version_id`, `page_setup` for upload) but the machine-readable schema is
empty, so a generated client gets no types and an integrator has to guess field names or make a live
call to find out.

Severity: low, worked around by recording real responses into a cassette and writing the client
against those. Not blocking.
