# SuperDocs use-case builds

Built by Anjali Yadav for the SuperDocs engineering task. This folder contains the two assigned Task 2 builds; Task 1 is a separate private repository.

Two standalone Python builds for the Task 2 document workflow:

- `accessible-doc-kit`: accepts HTML and produces accessible HTML analysis plus PDF and DOCX exports. The AI stages address headings, lists, table headers, links, image alt text, and the document language attribute.
- `haccp-drafter`: accepts JSON entries containing `step` and `hazard`, places them into a HACCP draft, and exports DOCX, PDF, and Markdown verification output.

All output is a draft for professional review. HACCP placement is AI-assisted and the local classifier is only a disagreement signal, not a safety authority.

## Setup on Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r common\requirements.txt
python -m pip install -r accessible-doc-kit\requirements.txt
python -m pip install -r haccp-drafter\requirements.txt
Copy-Item .env.example accessible-doc-kit\.env
Copy-Item .env.example haccp-drafter\.env
# Edit either .env and set SUPERDOCS_API_KEY
```

## Test

```powershell
python -m pytest -vv
```

The tests use mocked HTTP and local fixtures; no live API key is required.

## Run

```powershell
python accessible-doc-kit\main.py accessible-doc-kit\sample_input.html
python haccp-drafter\main.py "Chicken Nuggets" --batch haccp-drafter\sample_entries.json
```

Proposals require an interactive `y/yes` review before commit. For unattended automation, pass `--approve-all` explicitly. Exports do not consume operations. `--sample` runs only the first two accessibility stages to limit billable work.

## Optional live smoke test

With a valid key in `haccp-drafter/.env`, run this from the repository root:

```powershell
python common\live_smoke_test.py
```

This uploads a temporary document, sends one billable chat request, optionally approves its proposal, and exports Markdown. Upload and export are free. Use `--approve-all` only for unattended testing. The script never prints the API key.

## Tradeoffs and known limits

- The client uses 180-second requests and exponential retries because large document operations may be slow.
- Deterministic `Idempotency-Key` headers plus documented active-job lookup allow the client to recover an in-flight operation after a restart. The server must honor the header for complete retry deduplication.
- Local run state is atomic and locked per logical input; active async jobs are also discovered through the documented session-jobs endpoint before creating duplicate work.
- Accessibility after-analysis depends on HTML export. Markdown fallback is retained for graceful recovery but is not structurally equivalent HTML validation.
- The HACCP classifier does not override the model or certify food safety; professional review remains mandatory.


## Assignment Coverage

The assignment's Task 2 floor is implemented in both builds:

1. Upload a document into a persistent session.
2. Submit an edit instruction through SuperDocs chat.
3. Review proposed changes item by item and approve or reject each one.
4. Export the committed result.

Both builds use async HITL chat because synchronous chat auto-applies edits.
Pending changes are parsed defensively, including JSON-encoded strings. A
reviewer can approve some changes and reject others in the same batch. A
machine driver can use `--approve-all`, which is an explicit automation choice.

The builds also demonstrate visible staged work, bounded long-running polling,
budget stopping, atomic checkpoints, local run locking, active-job recovery,
untrusted source-data boundaries, and honest failure reporting. Exports and
downloads are not budgeted as operations.

## Project Structure

```text
accessible-doc-kit/
	main.py                 staged accessibility workflow
	analyze_structure.py    deterministic before/after analysis
	tests/                  network-free analyzer tests
haccp-drafter/
	main.py                 interactive and batch HACCP workflow
	template.py             template, classifier, and verification helpers
	tests/                  network-free HACCP tests
common/
	superdocs_client.py     REST, async HITL, polling, retries, budgets
	run_state.py            atomic checkpoints and OS locks
	live_smoke_test.py      opt-in live API verification
	tests/                  shared client/state/config tests
pytest.ini                root test discovery and import paths
```

## Evidence and Observed API Behavior

The live smoke test was run against a temporary session. It reached
`in_progress`, then `awaiting_approval`, displayed a structured proposal,
accepted a human decision, reached `completed`, and exported Markdown. The
export preserved the original text and contained the approved paragraph.

During development, synchronous chat returned document changes without an
approval envelope because that endpoint auto-applies changes. The implementation
was changed to the documented async HITL flow rather than treating that response
as approval metadata. The API also documents free structure reads, session job
listing, template upload, and async job polling; the client uses those confirmed
routes.

