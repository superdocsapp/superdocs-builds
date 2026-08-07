# Pull request draft — NOT SUBMITTED

> This file is the prepared PR description. Opening the pull request is
> Abhishek's call, not the agent's. Nothing here has been pushed.
>
> **Before opening it:**
> 1. `git log -p --all | grep -iE 'sk_[a-z0-9]{8}'` returns nothing (checked; re-check after any new commits).
> 2. Push the branch to the fork `AbhishekSharma55/superdocs-builds`.
> 3. Open the PR against `superdocsapp/superdocs-builds`, `main`.
> 4. Title and body below. **No email address** — CONTRIBUTING is explicit that
>    this is a public repo and addresses get scraped.

---

## Title

```
use-cases/AbhishekSharma55: a weekly digest that is edited not regenerated, and a multi-document GDD editor
```

## Body

**Abhishek Sharma**

Two projects in `use-cases/AbhishekSharma55/`, built on the REST API.

**[`weekly-digest/`](use-cases/AbhishekSharma55/weekly-digest/)** — one standing
document revised in place week after week instead of a fresh file each week, so
the reader always opens the same familiar document. Each week is a
single billable operation covering the status line, three standing sections, and
an archive that folds old weeks into rolled-up rows so it stays navigable (18
rows at week 52 rather than 51, with 11 rollups). Fourteen invariants are
re-derived from the document's own bytes after every week; a week that fails is
repaired by decomposing it into two simpler turns, or rolled back so the document
is never left corrupt, and every repair operation is counted. A control arm
regenerates the same digest from the same inputs so the cost claim has a number
behind it — the method, including what would falsify it, is committed in
`METHOD.md` before the results.

**[`gdd-editor/`](use-cases/AbhishekSharma55/gdd-editor/)** — a chat-driven
editor for long game design documents split across linked sub-documents
(mechanics, narrative, art bible), with image support for concept art. The
scenario it is built to pass — *a reviewer asks for a new GDD section plus one
linked sub-document, then requests a revision to one mechanic, and only the
correct section changes across both documents* — is executable as
`gdd scenario --live` and passes 20/20 checks in 6 operations. The proof is
re-derived from each document's bytes, not read from the API's change summary.

Both run on a shared client layer (`superdocs_kit/`) that keeps a durable ledger
of every operation spent, records every live call as a fixture so the 64 tests
run with no key and no network in 0.04 s, and proves "nothing else changed" from
the document rather than from a success message.

`bugs.md` has fifteen SuperDocs entries found while building — the highest-value
one being that `changes_summary` reported `"1 section edited, rest untouched"`
for a turn that had destroyed a table. Two of them are runnable for zero
operations: `repro/B10-multidoc-roster.sh` and `gdd probe-multidoc --live` both
reproduce a multi-document session returning a one-entry roster with every
document sharing `document_id: "doc_primary"`. Eight further entries are my own
mistakes and are in the same file, four of them cases where my own checking said
a document was fine when it was not.

Corpora are synthetic — the studio, the game and the people are fictional.

Built with Claude Code.

---

## Checklist against CONTRIBUTING.md

- [x] Fork, then a folder at `use-cases/<github-username>/<project-name>/` — two
      project folders under `use-cases/AbhishekSharma55/`, as CONTRIBUTING
      allows for more than one project.
- [x] Nothing outside that folder is modified. `git diff --stat upstream/main`
      touches only `use-cases/AbhishekSharma55/**`.
- [x] Name for public credit in the PR body: **Abhishek Sharma**.
- [x] One or two sentences on what each project does: above.
- [x] **No email address** anywhere in the PR body.
- [x] A `README.md` inside each project folder, covering what it does in plain
      language, how to run it, and which SuperDocs features it uses.
- [x] Environment variables are placeholders — `.env.example` ships
      `SUPERDOCS_API_KEY=your-key-here`; `.env` is gitignored and was verified
      ignored before the key was ever written.
- [x] **No secrets in the tree or in history.** The recording transport redacts
      anything key-shaped before a fixture is written, and there is a test that
      asserts it.
- [x] AI tooling disclosed: built with Claude Code, which is how I actually
      build.
- [x] Third-party code: none vendored. Runtime dependency is `httpx`;
      `pytest` for tests. The PNG encoder is stdlib `zlib` + `struct`, written
      here, so no image library is vendored or required.
- [x] MIT, per the repository.

## Not included, deliberately

- No demo video link — that goes on the submission form, not in a public PR.
- No MCP server. REST throughout; the reasoning is in `WALKTHROUGH.md` §4.
- `WALKTHROUGH.md` is written for the live conversation rather than for a
  reviewer of this repo, and stays in the folder for completeness.
