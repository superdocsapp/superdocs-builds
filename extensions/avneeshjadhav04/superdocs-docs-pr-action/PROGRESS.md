# PROGRESS.md — assumptions and decisions log

Assumptions made while building, logged per the task brief. Each entry: the
assumption, the reasoning, and where it lives in the code.

## Assumptions

1. **The doc target is a changelog (`CHANGELOG.md` by default).** A changelog
   is the canonical "documentation update on merge" artifact: every merge
   either deserves an entry or provably does not, which makes the skip logic
   honest and testable. Configurable via `doc_path` for repos that maintain a
   different doc. — `action.yml`, `decisions.py`

2. **REST API over MCP.** The card allows either surface. A CI runner has no
   MCP server dependency, and the four-call contract (upload, chat, approve,
   export) is the same on both surfaces. The MCP tool mapping is documented in
   the README. — `superdocs_client.py`

3. **The machine approves the proposed change; the human reviews the PR.**
   The card's "Review" surface is satisfied by `approval_mode:
   ask_every_time` + the approve call (the gate is an operation the flow
   exposes, exactly as behavior 4 of the shared task requires), and the human
   review is the pull request itself — the durable artifact the card asks for.
   The API auto-denies unattended reviews after ~1h, so a PR-gated flow is the
   only shape that survives CI latency. — `main.py`

4. **The merged PR's title/body are untrusted data.** They are quoted into the
   instruction as data, never executed as instructions, and the edit is scoped
   to one changelog entry. Tested: a title that tries to give orders produces
   a data-only entry. — `decisions.py::build_instruction`,
   `tests::InstructionBuilderTests`

5. **"Nothing needs saying" has five independent triggers.** Docs-only PR,
   skip marker, no change from SuperDocs (byte-identical export), entry
   already present, docs PR already open. Each is a separate early exit so a
   skip is provable, not assumed. — `decisions.py`, `main.py`

6. **The `pull_request.closed` event does not carry the file list.** The
   action derives changed files from the merge commit (`git diff sha^1 sha`),
   which is why checkout uses `fetch-depth: 0`. — `main.py`

7. **Proposed-change content can arrive as a JSON-encoded string.** The task
   doc warns this is the most common integration trap; the client parses both
   shapes. — `superdocs_client.py::_parse_changes`, tested.

8. **`awaiting_approval` has two flavours.** `continue_prompt` (large edit
   paused) is resumed via `/continue`, never `/approve`; the client branches on
   `metadata.awaiting_kind` exactly as the docs require. — tested.

9. **A docs PR for a merge that already exists is a duplicate.** Idempotency
   is checked by searching open PRs with the same title before doing any work.
   — `main.py::_existing_docs_pr`, tested.

## Cuts (defended)

- **No per-change human approval inside the action.** The card's review is the
  PR; a second approval round inside CI would block on a human who is not
  watching CI. The PR diff is the review surface.
- **No MCP mode.** REST covers the contract; MCP would add a server dependency
  to the runner for no behavioral gain. Documented as a future option.
- **No multi-doc support.** The action maintains one doc file per repo; a
  multi-file mode would multiply operations per merge for little value.
- **No PyGithub.** The first version used PyGithub (LGPL-3.0, weak copyleft).
  Swapped for a ~120-line `github_client.py` that calls the GitHub REST API
  directly with `requests`, so the dependency tree is permissively licensed
  only (MIT/Apache/BSD). Cost: a few more lines and manual pagination if the
  open-PR list ever grows past one page (unlikely for a docs-PR queue).

## Known limitations

- The changelog entry is only as accurate as SuperDocs' summary of the merged
  PR; the human review is the safety net.
- `git diff` fallback for changed files requires `fetch-depth: 0`; without it,
  a docs-only PR may not be detected and the action may run when it should
  skip (it will still skip if SuperDocs produces no change).
- The action does not auto-merge; a human must merge the docs PR.

## Live-test findings (demo repo: avneeshjadhav04/docs-pr-demo)

Verified end to end on a real repository with a real SuperDocs API key:

- **Feature merge -> docs PR opens.** PR #8 merged, action drafted the entry
  ("- feat: slugify names (#8)"), opened PR #9 with a one-entry diff. The
  diff touched only CHANGELOG.md.
- **Docs-only PR -> skip.** PR #10 (README change) merged; action logged
  "changed only documentation" and exited 0.
- **Skip marker -> skip.** PR #11 with `[skip-docs]` in the title merged;
  action logged "matches a skip pattern" and exited 0.

Three real bugs found and fixed during the live run:

1. **`${{ secrets.X }}` is invalid inside action.yml.** The `secrets` context
   exists only in workflow files, not action manifests; the runner rejected
   the manifest at load time. Fixed by removing the expression from the input
   description. (Found via run log, not docs.)
2. **Session-level `Content-Type: application/json` broke multipart uploads.**
   `requests` will not override an existing Content-Type header when sending
   `files=`, so the upload body went out as JSON and the server returned 422
   "Field required: file". Fixed by setting only the Authorization header on
   the session; `json=` sets Content-Type per request.
3. **A completed job can carry `metadata.pending_changes: None`.** The AI
   applied the edit directly (approval_mode was honored, but the job completed
   with no pending-changes array), and `_parse_changes` crashed on None.
   Fixed by treating None/missing as an empty list and logging the AI's
   response text for diagnostics.

Also observed: GitHub blocks Actions-created PRs unless the repository setting
"Allow GitHub Actions to create and approve pull requests" is enabled
(403 "GitHub Actions is not permitted to create or approve pull requests").
Documented in the README as a setup requirement.
