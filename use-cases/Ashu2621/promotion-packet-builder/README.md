# Promotion Packet Builder

Built by **Ashutosh** for the SuperDocs engineering task.

This local web app assembles a self-review or promotion case from a draft/template and supplied
evidence artifacts. It uses the official SuperDocs MCP server for the complete minimum contract:

1. upload the active document and optional reusable template;
2. upload and search multiple evidence artifacts without changing the document;
3. list and select reusable templates;
4. send an async evidence-grounded edit instruction with `ask_every_time`;
5. poll and show proposed changes, including the doubly encoded nested JSON shape;
6. require a structured citation with an exact quote from a supplied artifact and disable ungrounded approvals;
7. verify job/session ownership, require exactly one decision per current change and support mixed batches;
8. repeat review for every revised round and enable export only after the reviewed job is terminal; and
9. stream a size-bounded strict-fidelity DOCX or PDF export from an allowlisted signed host.

The SuperDocs key is read only by the FastAPI backend. It is never sent to browser JavaScript, MCP
arguments, URLs or export-download hosts. Cross-session memory/search is explicitly disabled. Stable
idempotency keys are created once per browser intent and reused on retries for upload, search, edit,
review and export.

## Run

Requires Python 3.12+ and one development SuperDocs API key. After copying `.env.example` to `.env`,
the complete local app starts with one command:

```powershell
Copy-Item .env.example .env
.\run.ps1
```

Open `http://127.0.0.1:8080`. Use only synthetic, public or personally owned documents.

## Offline tests

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m pytest -q
```

The tests use a fake MCP dependency and verify document/attachment/template routing, search, stable
idempotent replay, backend-only safe edit flags, the nested proposed-change parse, complete mixed-batch
decisions, citation enforcement, large-file presigned streaming and streamed provider export without a
live key. They also cover cross-session job rejection, revised-round export blocking and signed-URL
validation.

## SuperDocs surfaces

- MCP Streamable HTTP
- document upload
- attachments / multi-document grounding and explicit search through the active chat
- reusable templates
- async chat and job polling
- Review/HITL approval
- DOCX/PDF export

## Limitations

This public contribution is a bounded local demo, not a multi-tenant hosted service. It accepts the
provider-native DOCX, PDF, Markdown, text, RTF, HTML, TeX and zipped-LaTeX formats. Each file is limited
to 100 MB; files over 100 KB use a presigned,
64-KiB-chunk streaming upload instead of base64-in-JSON, and export downloads are streamed with a
100 MB response cap. Signed upload/export hosts must match `SUPERDOCS_SIGNED_URL_HOSTS`. Saving a
reusable template remains limited to 100 KB because the current template tool is inline-only. It accepts
up to 20 evidence attachments and intentionally searches only the active session.

The app keeps opaque provider session/job identifiers and its idempotency ledger in process memory, so a
server restart requires a new local workflow. It does not independently prove source facts are true; it
proves that every approved change carries an exact quote associated with a supplied artifact and exposes
that link for human judgment. The private agent-system submission adds durable PostgreSQL checkpoints, tenant authorization,
audit history, incremental analysis, crash recovery, rich-text/Word clients and verified export reparsing.

Measured results and their limitations are in [CASE-STUDY.md](CASE-STUDY.md).

## Automation disclosure

Ashutosh used AI-assisted coding, research, and test orchestration while building
this candidate project. Ashutosh is the sole applicant and is responsible for
source verification, security decisions, final review, submission, demo, and
live discussion. AI-assisted tooling prepared this project and, on Ashutosh's
explicit instruction, opened its GitHub contribution. It did not contact
prospects, send email or bug reports, submit the application, or impersonate a
human.
