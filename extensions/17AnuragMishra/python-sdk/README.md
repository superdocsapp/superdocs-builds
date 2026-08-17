# SuperDocs Python SDK 0.2

A PEP 561 typed SDK for the current SuperDocs REST API, with matching synchronous and asynchronous clients.

> Built by Anurag Mishra for the SuperDocs Round 2 engineering task.

## Install and verify

```bash
pip install superdocs-python
```

Local development:

```bash
python -m pip install -e ".[dev]"
python scripts/run_tests.py
python -m ruff check src tests
python -m mypy src
python scripts/build_package.py
```

## Core usage

```python
from superdocs_sdk import ApprovalDecision, SuperDocsClient

with SuperDocsClient.from_env() as client:
    uploaded = client.upload_document("agreement.docx", session_id="deal-123")
    job = client.chat_async(
        session_id="deal-123",
        message="Make the rights scope precise.",
        approval_mode="ask_every_time",
        response_mode="compact",
    )
    paused = client.wait(job.job_id)
    changes = paused.metadata["pending_changes"]
    client.approve_change(
        session_id="deal-123",
        job_id=job.job_id,
        approved=True,
        changes=[ApprovalDecision(change_id=item["change_id"], approved=True) for item in changes],
    )
    completed = client.wait(job.job_id)
    exported = client.export_document(session_id="deal-123", format="docx")
```

`AsyncSuperDocsClient` exposes the same categories and payload contract. Its waits and retry backoff use `asyncio.sleep`; progress and pagination are async iterators.

## API surface

- Sessions: create, list/page/iterate, history, delete.
- Documents: list/page/iterate, detail, archive, restore, upload, export.
- Chat: synchronous response, durable async job, polling wait, SSE progress, double-parsed proposed-change batches.
- Approvals: global decision plus typed per-change decisions and feedback.
- Files: automatic multipart upload at or below 100 KB; above that, `POST /v1/uploads` → credential-free presigned `PUT` → `POST /v1/uploads/{upload_id}/process`.
- Export: session, inline HTML, or presigned `upload_id`; exactly one source is required.

## Reliability and security

- Mutations receive an idempotency key before the first attempt, and retries reuse it.
- Retryable `408`, `429`, and `5xx` responses use `Retry-After` or bounded exponential backoff. Other `4xx` responses fail immediately.
- Every network method supports a per-call timeout.
- SSE uses the transport's authorization header; the API key never appears in a URL.
- Presigned storage PUTs use only storage-provided headers, preventing bearer-token leakage to cloud storage.
- Context managers close owned HTTP resources, and `repr()` redacts credentials.
- Specific exceptions include authentication, validation, conflict, rate-limit, server, transport, and timeout failures, with status/code/request ID/retryability/suggested action.

## Proof

One shared parity suite drives both clients and covers request shape, idempotent retries, nonblocking async backoff, typed errors, pagination, per-call timeouts, context cleanup, streaming double parse, human-input waits, large upload PUT/process, and credential-leak prevention. Source and wheel distributions include `py.typed`.
