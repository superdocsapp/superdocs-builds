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

### 2026-08-11 — One SuperDocs session per document, not one per run

Forced by a live finding, not chosen on taste. A session holds **one active job at a time**, and a
job parked at `awaiting_approval` keeps holding it for as long as the human takes to review — a
second request to that session gets `409 session_busy` indefinitely ([BUGS.md](BUGS.md) #8).

Since human review is unbounded in time, one session per run would mean the first document awaiting
review blocks every other document in the run. One session per document removes the coupling
entirely, and has a second benefit that pays for behaviour 9: two concurrent runs cannot collide,
because they never share a session.

Cost: one session per file instead of one per run. Sessions are free; only chat turns are billed,
and the count of those is unchanged.

### 2026-08-11 — Lint instructions must be phrased as edit commands

The first live lint attempt used "review this document and propose corrections" and got back *"I
wasn't able to determine an action for that request"* — billed, with nothing to show. Rephrasing to
"edit this document so it complies with the uploaded style guide, making the smallest change that
fixes each violation" produced exactly the right proposals on the same document.

So `approval_mode: "ask_every_time"` is what converts an edit into a reviewable proposal; the
instruction itself must still command an edit. Recorded as [BUGS.md](BUGS.md) #3, and the prompt in
`docs_lint` carries a comment pointing at it so nobody "improves" it back.

### 2026-08-11 — Run cost is read from `result.usage.ops_charged`, not a whoami delta

The original plan sampled `GET /v1/agents/whoami` either side of a run and reported the difference.
That measures nothing: whoami reports only the free-tier counter and omits the promo bucket the work
is actually billed against, so the delta across a real billed operation is zero
([BUGS.md](BUGS.md) #1). Cost now comes from each job's own `result.usage`, which carries
`ops_charged` per turn. There is a test pinning both halves of this.

---

## Cuts made, and why

*(Nothing cut yet. Recorded here as it happens, for the Task 4 write-up.)*

---

## Bugs, rough edges and confusing moments in SuperDocs

Collected in **[BUGS.md](BUGS.md)**, in the shape the task document asked for: what I did, what I
expected, what happened instead, how badly it blocked me, and a reproduction.

Kept in its own file rather than inline here because it is a deliverable in its own right — it
feeds the submission form's first question and the email to the team — and because it should stay
readable by someone who does not care about this project's build log.
