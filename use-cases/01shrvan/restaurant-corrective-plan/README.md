# Restaurant Corrective Plan

Built by Shrvan Benke for the SuperDocs Round 2 task.

This app turns cited restaurant inspection violations into a code-by-code corrective action plan. It keeps one review card per cited violation, requires a separate corrective action and owner for each item, and refuses export when coverage is incomplete or any item is undecided.

## Run

```powershell
.\run.ps1
```

Then open `http://127.0.0.1:8000`.

Optional live SuperDocs smoke test:

```powershell
$env:SUPERDOCS_API_KEY="your-key-here"
cd backend
.\.venv\Scripts\python.exe -m app.live_demo
```

Do not commit real keys. `.env.example` is a placeholder only.

## Tests

```powershell
cd backend
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"
.\.venv\Scripts\python.exe -m pytest -q
```

Current local result: `19 passed`. The deliberate broken-generator check was also run: making the offline drafter emit one blended action and owner made `test_offline_generator_produces_one_verified_item_per_violation` fail.

## SuperDocs Features Used

- Template: the base HTML document has one structural section per violation code.
- Chat editing: live smoke test uses `POST /v1/chat/async` with `approval_mode: "ask_every_time"`.
- Human approval: the client polls for `awaiting_approval` and approves each returned `change_id`.
- Export: live smoke test exports DOCX through `POST /v1/documents/export`; offline UI exports HTML only.

Live smoke test on 2026-08-06: 3 changes approved, DOCX exported, 37,045 bytes. The exported file is written to ignored `out/`.

## Sample Data

The sample restaurant, inspection report, and health department are fictional. The three sample FDA Food Code-style violations cover handwashing sink hot water, hot holding for cooked rice, and fryer-line cleaning.

## Screenshot

Screenshot placeholder: capture the review screen after the final demo pass.

## Limitations

- Offline drafting is deterministic and intentionally conservative; it is a fallback, not a claim that no model is needed.
- Offline export currently returns HTML. DOCX/PDF export is available through the live SuperDocs smoke path.
- The verifier rejects copied actions, copied owners, invented codes, empty reports, and boilerplate actions, but very short vague actions such as "Will be addressed" are a documented limitation to tighten next.
- This is not an 8D root-cause investigation and does not claim a health department will accept the plan without human review.

