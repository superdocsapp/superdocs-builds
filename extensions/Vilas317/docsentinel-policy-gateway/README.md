# DocSentinel Policy Gateway

A standalone policy gateway that sits in front of the SuperDocs document tools. It applies a centralized security policy before forwarding requests to the SuperDocs REST API.

## What it does

The gateway protects the four core SuperDocs operations:

- **Upload** a document
- **Chat** with an edit instruction
- **Approve** proposed changes
- **Export** the finished document

Every request passes through the same policy pipeline:

```text
Request
   |
   v
Tool allowlist
   |
   v
Sensitive-content scan
   |
   v
Team quota
   |
   v
SuperDocs API
   |
   v
Audit event
```

Sensitive requests are rejected before quota is consumed. Audit events are hash-chained and do not store document payloads.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Set `SUPERDOCS_API_KEY` in `.env` using a real key locally. Never commit it.

Start the gateway:

```powershell
uvicorn app.main:app --reload
```

Health check:

```text
GET /health
```

Gateway endpoints:

```text
POST /gateway/v1/documents/upload
POST /gateway/v1/chat
POST /gateway/v1/chat/{session_id}/approve
POST /gateway/v1/documents/export
```

Provide the team with `X-Team-ID`. The included policy gives the `default` team 100 operations.

## Policy configuration

Edit `config/gateway_policy.yaml` to configure:

- allowed tools
- sensitive-content scanning
- block or mask behavior
- per-team quotas
- audit settings

The gateway reads the policy at startup. The public example intentionally contains no credentials.

## Sensitive-content protection

The example scanner detects email addresses, phone numbers, US SSNs, and common `sk_`/`pk_` API-key formats. Block mode is enabled by default.

## Tests

The tests use fake downstream responses and therefore do not require a live SuperDocs API key:

```powershell
pytest -q
```

## SuperDocs integration

This project uses the SuperDocs REST API as the downstream document service. The gateway deliberately forwards documents and edit requests through the host API instead of manipulating raw Word XML.

## Security notes

- Never commit `.env` or API keys.
- Audit events contain request metadata, not document content.
- Large uploads are scanned in chunks and the original file stream is forwarded to the downstream upload endpoint.
- The gateway fails closed on tool, sensitive-content, and quota policy violations.
