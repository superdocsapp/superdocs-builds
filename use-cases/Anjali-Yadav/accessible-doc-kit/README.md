# Accessible-document standard kit


 ## What It Does

 This build accepts a structurally messy HTML document and guides it through
 an accessibility cleanup workflow. It checks heading hierarchy, real list
 semantics, table headers and scopes, descriptive link text, image `alt` text,
 and the HTML language attribute.

 The result is a draft for human review, with a generated before/after
 structure report and PDF/DOCX exports. It does not claim WCAG certification.

 ## SuperDocs Features Used

 - Base64 document upload into a persistent session.
 - Async chat editing with `approval_mode=ask_every_time`.
 - Per-change human approve/deny decisions.
 - JSON-encoded proposal parsing and fail-closed validation.
 - Free PDF, DOCX, HTML, and Markdown export paths.
 - Long-running job progress polling with a bounded deadline.

 ## Inputs and Outputs

 Input is UTF-8 HTML, for example `sample_input.html`. The application sends
 the document to SuperDocs, then runs six ordered edit stages. `--sample` runs
 only the first two stages to keep a live demonstration small.

 Outputs are written to `output/` by default:

 - `accessible_output.pdf`
 - `accessible_output.docx`
 - `accessible_output.html` when HTML export is available
 - `accessible_output.md` as a readable fallback when HTML export is unavailable
 - `structure_report.json` containing measured before/after results

 ## Setup

 From the repository root on Windows PowerShell:

 ```powershell
 py -m venv .venv
 .\.venv\Scripts\Activate.ps1
 python -m pip install -r common\requirements.txt
 python -m pip install -r accessible-doc-kit\requirements.txt
 Copy-Item .env.example accessible-doc-kit\.env
 ```

 Edit `accessible-doc-kit\.env` and set:

 ```text
 SUPERDOCS_API_KEY=your-key-here
 SUPERDOCS_BUDGET_FLOOR=20
 ```

 The `.env` file is local-only and ignored by Git. Never put a real key in a
 README, fixture, log, or commit.

 ## Run

 ```powershell
 python accessible-doc-kit\main.py accessible-doc-kit\sample_input.html
 ```

 Quota-friendly live run:

 ```powershell
 python accessible-doc-kit\main.py accessible-doc-kit\sample_input.html --sample
 ```

 Each proposed change is displayed before commit. Enter `y` or `yes` for each
 change. For explicitly unattended automation only:

 ```powershell
 python accessible-doc-kit\main.py accessible-doc-kit\sample_input.html --sample --approve-all
 ```

 ## Architecture

 `main.py` owns the staged workflow: analyze locally, upload once, submit one
 async instruction per stage, poll until approval is needed, collect one
 decision per change, approve the batch, checkpoint completion, export, and
 measure the final HTML. `analyze_structure.py` is deterministic local
 validation and never treats model prose as the report. Shared HTTP, retries,
 budgeting, idempotency headers, polling, and approval parsing live in
 `../common/superdocs_client.py`; atomic state and per-input locking live in
 `../common/run_state.py`.

 The uploaded document is explicitly treated as untrusted data in every edit
 instruction. The model is not allowed to turn document text, attributes,
 links, or metadata into workflow instructions.

 ## Resumption and Failure Behavior

 Run state is keyed by the input content hash, written atomically, and locked
 per logical input. Re-running the same input resumes completed stages rather
 than redoing them. API retries carry deterministic `Idempotency-Key` headers.
 Known long requests show progress and stop at a polling deadline. A rejected
 stage remains incomplete and can be reviewed again.

 ## Tradeoffs and Known Limits

 - Stages are sequential to preserve document ordering and approval clarity;
	 this costs throughput but avoids competing edits to one session.
 - HTML export is required for a trustworthy structural after-report. If it
	 fails, Markdown is saved but deliberately not analyzed as HTML.
 - PDF/DOCX are exported deliverables; this build does not independently run a
	 PDF accessibility conformance checker.
 - Local locks protect processes on one machine. Duplicate prevention after a
	 client crash still depends on SuperDocs honoring `Idempotency-Key`.
 - The live smoke test is intentionally outside CI because it requires a
	 secret and consumes an AI operation.

 ## Tests

 Tests are network-free and use local HTML fixtures plus mocked HTTP:

 ```powershell
 python -m pytest accessible-doc-kit/tests common/tests -vv
 ```

 The repository-wide command is:

 ```powershell
 python -m pytest -vv
 ```

 ## Demo

There is no hosted deployment or video link. The reproducible demo is the
PowerShell command above; the companion live smoke test is documented in the
repository README.

