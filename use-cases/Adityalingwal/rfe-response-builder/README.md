# RFE Response Builder

Officer's notice in — attorney-ready response package out.

When USCIS issues a Request for Evidence, an attorney has to answer every
concern in it, on a deadline, from a petition that may run hundreds of
pages. This tool reads the officer's notice, splits it into the individual
requests, finds the petition material that answers each one, and drives
SuperDocs to draft a response section per request — then stops at a human
review gate. Nothing is applied or exported until a person approves the
proposed changes. Before the result is ever called filed-ready, the export
is verified: quotes verbatim, citations real and complete, evidence gaps
stated honestly.

Built for the SuperDocs engineering task. It is attorney-support drafting
software, not legal advice, and it never decides eligibility.

![System flow](docs/flow-diagram.svg)

## Two doors, one core

The same five operations are available two ways: a command line, and an
MCP server. Both call the same functions in `rfe.py`, so there is no
second implementation to drift.

| Operation | Command line | MCP tool | Bills |
|---|---|---|---|
| Is the key valid | `rfe.py check` | `check_key()` | no |
| Parse the notice, build the coverage checklist | `rfe.py preview` | `preview_case()` | no |
| Have the model judge coverage | `rfe.py judge` | `judge_coverage()` | should bill; has charged 0 so far |
| Upload and draft, then stop for review | `rfe.py draft` | `draft_response()` | yes |
| Carry the decision, export, verify | `rfe.py decide approve` (all or nothing) | `decide_changes()` (all, or change by change) | sometimes |

The steps are separate on purpose. `draft` stops at the proposed changes
and waits — nothing reaches the document until the next step carries an
explicit decision. That pause is the human gate, not an unfinished step.

The decision can also be made in the SuperDocs app's own Review view —
it is the same job. Even then, run `decide` once at the end: it notices
the decision is already made, so it only downloads the export and
verifies it.

### Door 1 — the command line

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest tests/        # 138 tests, all offline — no API key
.venv/bin/python rfe.py preview          # parse + coverage checklist (free, offline)

cp .env.example .env      # put your real key in .env — never commit it
.venv/bin/python rfe.py check             # key valid? (free)
.venv/bin/python rfe.py judge             # AI coverage judgement
.venv/bin/python rfe.py draft             # upload + draft, stops for review
.venv/bin/python rfe.py decide approve    # or reject; then export + verify
```

Run these one at a time. `preview` reads the bundled fictional H-1B case
in `data/` and writes `output/checklist.md` — one entry per officer
request, with the petition sections it located and a coverage verdict.

### Door 2 — an MCP client

Register the server once, from the repo folder:

```bash
claude mcp add rfe-response-builder -- "$(pwd)/.venv/bin/python" "$(pwd)/mcp_server.py"
```

Or, for a client that reads a config file:

```json
{
  "mcpServers": {
    "rfe-response-builder": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/mcp_server.py"]
    }
  }
}
```

Then ask the client to run the tools in the table above; call them one at
a time as well. Each takes an optional `case_dir` — a folder holding
`notice/` (one file) and `petition/` (the original petition documents).
Leave it out to use the bundled sample case. `decide_changes` takes
either `approve_all=true` or a per-change list, where feedback on a
single change makes the model re-propose just that one.

`MAX_OPS_PER_RUN` in `.env` (default 10) caps how many billable calls one
run may make — a run being the whole cycle from `draft` to the final
export. The count is saved in `output/run_state.json` between commands,
so `decide` carries on from where `draft` stopped. Once the cap is
reached, the run refuses the next billable call.

## What it does

- Parses the officer's notice into individual requests — across six
  layout styles and `.md`/`.txt`/`.pdf`/`.docx`.
- Locates petition material per request with deterministic, traceable
  word-overlap retrieval — every match can be traced to the words that
  produced it. Petition files in any other format are skipped, and the
  run lists them by name so nothing drops silently.
- Has SuperDocs' model judge coverage per request (answered / partially /
  not provided), then code verifies the judgement: an "answered" with no
  located material is overridden to "not provided".
- Builds the response skeleton in code — structure, officer quotes,
  citations, coverage table are deterministic; the model only writes
  prose into per-request placeholders.
- Stops at a human gate: proposed changes are written out for review;
  approve, reject, or reject-with-feedback (which makes the model
  re-propose; feedback through the MCP door) — over as many rounds as it
  takes.
- Verifies the export before calling it filed-ready: no surviving
  placeholders, officer quotes untouched, every request keeps its
  section, every unanswered request's section says its evidence is
  missing, every citation verbatim, from a real petition file, and none
  silently removed. The
  comparison is by words — markdown syntax SuperDocs rewrites on export
  (a `*` gains a backslash, a `<br>` in a table cell disappears) is not
  mistaken for a changed quote. The verdict is written next to the export as
  `output/verification.md` — filed-ready yes or no, and every failure
  by name — so the folder answers the question without the terminal.

Everything a run produces lands in `output/`: `checklist.md` (preview),
`skeleton.md` (the code-built document that was uploaded),
`pending_changes.md` / `.json` (what is waiting for review),
`run_state.json` (the session, job and count a pending run resumes
from; deleted when the run finishes), and after the decision
`final-response.md`, `final-response.docx` and `verification.md`. Each
run overwrites the last.

## SuperDocs surface

| Call | Used for |
|---|---|
| `POST /documents/upload-base64` | uploading the skeleton |
| `POST /attachments/upload-base64` | attaching the petition documents |
| `POST /chat` | the coverage judgement |
| `POST /chat/async` | drafting and re-drafting |
| `GET /jobs/{id}` | polling the draft job |
| `POST /chat/{session}/approve` | carrying the human decision |
| `POST /documents/export` | downloading the final document |

The export returns the same document twice — once as `.md`, once as
`.docx`. The verification checks read the `.md` copy.

## Evidence

| Claim | Proof |
|---|---|
| 138 automated tests, no key, no network | `.venv/bin/python -m pytest tests/` |
| Blind-tested on 9 unseen fictional cases (7 visa types, 7 notice layouts, 62 requests, independent answer keys) | `tests/blind/` |
| Dangerous misses ("answered" where evidence was missing): 1/62, caught by the human gate in review | blind protocol notes in `NOTES.md` |
| 5 parser defects found blind were fixed with regression tests | `tests/test_parse_notice_formats.py` |
| Full live run, hardest case (O-1A, 8 requests, PDF): first round invented wage data — the gate rejected it and export verification refused it; the corrected rerun passed through three review rounds | `NOTES.md` |
| Full live run through the MCP door on an unseen R-1 case, decisions made in the SuperDocs review UI | `NOTES.md` |

## Known limitations

- No OCR — scanned, image-only PDFs are refused, not read. Legacy `.doc`
  is not supported (`.docx` is).
- There is no next request after the last one to mark where it ends, so
  the parser stops at the first all-caps line (heading-style notices) or
  the first blank paragraph (list-style). The end of the last request
  can get cut — check its officer quote in the checklist.
- A very short notice gives the locator few words to match, so it says
  "partially" more often. That direction is chosen on purpose: a false
  "partially" costs one extra look, a false "answered" gives false
  comfort before a legal deadline.
- The chat API takes at most 100,000 characters per message. On a very
  large case the whole petition does not fit, so the judge reads shorter
  excerpts per request.
- One active run at a time: drafting a second case while one is pending
  is refused with instructions, not queued.
- The operation counter is an estimate, not a bill. The drafting
  endpoint does not report what it charged, so the tool counts 1 for
  that call instead of the real number.

## Data & privacy

Everything in `data/` and `tests/` is fictional and marked as such —
invented people, employers, and filings, written for this task.

## Built by

Aditya Lingwal, for the SuperDocs engineering task.
