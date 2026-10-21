# HACCP / food-safety-plan drafter

 # HACCP Draft Plan Builder

 ## What It Does

 This build accepts food-process entries containing one `step` and one
 `hazard`, then creates a structured HACCP draft. The AI places each entry
 under Hazard Analysis, Critical Control Points (CCPs), Monitoring Procedures,
 or Corrective Actions.

 The local classifier is an independent placement hint and disagreement signal;
 it never silently overrides the model. The output remains a draft and must be
 reviewed by a qualified food-safety professional before use.

 ## SuperDocs Features Used

 - Reusable HACCP template registration plus persistent document upload.
 - Async chat editing with `approval_mode=ask_every_time`.
 - Per-change human approve/deny decisions, including mixed batch decisions.
 - Second JSON parsing for document and approval payloads.
 - Session history and revert helpers.
 - DOCX, PDF, and Markdown export.
 - Export-time disclaimer and section-placement evidence.

 ## Inputs and Outputs

 Batch input is UTF-8 JSON containing objects with required string fields:

 ```json
 [
	 {
		 "step": "Cooking chicken nuggets",
		 "hazard": "Cook to an internal temperature of 165F for 15 seconds"
	 }
 ]
 ```

 Outputs are written to `output/` by default:

 - `haccp_plan.docx`
 - `haccp_plan.pdf`
 - `haccp_plan_verify.md`
 - `haccp_placement_verification.json`
 - `session_log.json`

 The Markdown verification export must retain the professional-review note.
 Placement verification is evidence for review, not a regulatory certification.

 ## Setup

 From the repository root on Windows PowerShell:

 ```powershell
 py -m venv .venv
 .\.venv\Scripts\Activate.ps1
 python -m pip install -r common\requirements.txt
 python -m pip install -r haccp-drafter\requirements.txt
 Copy-Item .env.example haccp-drafter\.env
 ```

 Edit `haccp-drafter\.env` and set:

 ```text
 SUPERDOCS_API_KEY=your-key-here
 SUPERDOCS_BUDGET_FLOOR=20
 ```

 The `.env` file is local-only and ignored by Git. Never put a real key in a
 README, fixture, log, or commit.

 ## Run

 Interactive mode:

 ```powershell
 python haccp-drafter\main.py "Chicken Nuggets"
 ```

 Repeatable batch mode:

 ```powershell
 python haccp-drafter\main.py "Chicken Nuggets" --batch haccp-drafter\sample_entries.json
 ```

 Each proposal is displayed and reviewed one change at a time. Enter `y` or
 `yes` to approve a change; any other response denies it. For explicitly
 unattended automation only:

 ```powershell
 python haccp-drafter\main.py "Chicken Nuggets" --batch haccp-drafter\sample_entries.json --approve-all
 ```

 Useful controls include `--restart`, `--list-versions`, and `--revert-to`.

 ## Architecture

 `template.py` owns the HACCP skeleton, professional-review disclaimer,
 classifier, untrusted-data prompt boundaries, and exported placement check.
 `main.py` owns template/upload setup, interactive or batch input, async job
 polling, per-change approval, checkpointing, and export verification.
 Shared HTTP, retries, budget tracking, idempotency headers, polling, and JSON
 normalization live in `../common/superdocs_client.py`; atomic state and
 per-input locking live in `../common/run_state.py`.

 The process and hazard fields are delimited as untrusted data. Embedded
 commands or policy claims in an entry are data for classification, not
 instructions to the agent.

 ## Resumption and Failure Behavior

 Batch and interactive runs use a stable state key, atomic checkpoint writes,
 and a per-run OS lock. Approved entries are skipped on resume; rejected or
 no-change entries remain incomplete. Async jobs report progress, fail clearly
 on terminal errors, and stop at a bounded polling deadline. Billable chat and
 approval calls use the configured budget floor and deterministic idempotency
 keys; exports are free.

 ## Tradeoffs and Known Limits

 - Entries are processed sequentially so one session preserves HACCP ordering
	 and every proposal can be reviewed before commit.
 - The classifier is deliberately conservative and advisory. It cannot certify
	 hazard analysis, critical limits, or regulatory compliance.
 - Placement verification searches the exported Markdown under the expected
	 heading. It catches obvious misplacement but does not replace professional
	 review or a domain-specific HACCP audit.
 - Duplicate recovery after an unrecoverable client crash depends on the
	 SuperDocs server honoring `Idempotency-Key`.
 - Template and version-history helper routes depend on the corresponding
	 SuperDocs API contract; the core upload/chat/approve/export workflow does
	 not depend on them.
 - The live smoke test is intentionally outside CI because it requires a
	 secret and consumes an AI operation.

 ## Tests

 Tests are network-free and cover classification, prompt boundaries,
 disclaimer retention, parsing, retries, budgets, locking, and state:

 ```powershell
 python -m pytest haccp-drafter/tests common/tests -vv
 ```

 The repository-wide command is:

 ```powershell
 python -m pytest -vv
 ```

 ## Demo

There is no hosted deployment or video link. The repeatable batch command
above is the reproducible demo, and `common\live_smoke_test.py` provides a
small live async HITL verification against SuperDocs.

