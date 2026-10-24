# Webhook Document Receiver

Turn an authenticated product event into durable, reviewable document work in SuperDocs.
The HTTP request verifies and persists an event quickly; a PostgreSQL-leased worker performs
the external workflow, pauses for item-level decisions when configured, exports the approved
document, and records a bounded artifact and transition timeline.

## What is implemented

- Generic HMAC and GitHub raw-body signature verification.
- Timestamp freshness for Generic HMAC, strict delivery IDs, and constant-time comparison.
- PostgreSQL uniqueness on provider plus delivery ID, including replay and collision behavior.
- YAML routes with strict provider, workflow, approval, model, target, and export validation.
- Generate routes using named, uploaded SuperDocs templates.
- Edit routes bound to a configured SuperDocs File ID from the environment—never event URLs.
- Durable polling, worker leases, expired-lease recovery, bounded retries, and
  `needs_attention` for ambiguous external effects.
- Distinct SuperDocs change-review and continuation wait kinds.
- Manual per-change approve/reject decisions and explicitly configured automatic approval.
- Management-token-protected status, timeline, review, retry, and artifact endpoints.
- Idempotent Template Library bootstrap from checked-in HTML fixtures.
- Local Docker Compose and a paid Render Blueprint with PostgreSQL 18.

Offline boundary tests and real-PostgreSQL integration tests cover these behaviors. A live
SuperDocs call and a clean Docker/Render deployment still require the operator's credentials
and environment and are intentionally not claimed by this repository.

## Architecture

```text
signed JSON request
  -> body limit and content-type check
  -> raw-body provider authentication
  -> route match and field allowlist
  -> atomic PostgreSQL delivery + job
  -> 202 response

leased worker
  -> start or resume one external step
  -> poll SuperDocs async job
  -> persist proposed changes
  -> wait for decisions
  -> submit exact decisions
  -> export approved document
  -> bounded artifact + digest + audit timeline
```

PostgreSQL is the only local source of truth. The delivery guarantee is **at-least-once local
execution with guarded external effects and explicit reconciliation**, not exactly once across
PostgreSQL and SuperDocs.

## Quick start

Requirements: Docker with Compose and a SuperDocs API key.

```bash
cp .env.example .env
# Replace every placeholder secret in .env.
docker compose up --build
```

The setup container applies idempotent migrations and uploads any missing required templates
before the API and worker start. Template files are user- or organization-scoped by SuperDocs;
run bootstrap with the same API key the worker will use.

```bash
python scripts/migrate.py
python scripts/bootstrap_templates.py
```

Liveness is `GET /health/live`; readiness is `GET /health/ready`.

## Route contract

Routes live in `routes/routes.yaml`. Each accepted event stores a full route snapshot, so an
in-flight delivery does not silently change behavior when the YAML file changes.

Generate workflow:

```yaml
workflow:
  mode: generate
template:
  name: incident-report
  required: true
```

SuperDocs discovers uploaded templates from the trusted instruction. The worker always adds
the configured template name to that instruction; webhook payload text remains untrusted data.

Edit workflow:

```yaml
workflow:
  mode: edit
  target:
    source: configured_file
    file_id_env: PROJECT_STATUS_FILE_ID
```

The referenced environment value must be a safe SuperDocs document ID. The worker retrieves
the File HTML with `include_html=true`, opens the File into its session, and sends that HTML
unchanged so `data-chunk-id` structural addresses survive the round trip.

The current documented SuperDocs export contract supports `doc` and `docx`; route validation
therefore rejects other formats instead of deferring an unsupported choice to runtime.

## Generic HMAC protocol

Send `POST /v1/webhooks/generic-hmac` with `Content-Type: application/json` and:

| Header | Value |
|---|---|
| `X-Webhook-ID` | Stable safe delivery ID, maximum 128 characters |
| `X-Webhook-Timestamp` | Unix seconds |
| `X-Webhook-Signature` | `sha256=<hex HMAC>` over `<timestamp>.<delivery ID>.<raw body>` |

```python
import hashlib
import hmac
import json
import time

secret = "replace-with-your-webhook-secret"
body = json.dumps(
    {"type": "incident.resolved", "incident_id": "inc_123"},
    separators=(",", ":"),
).encode()
timestamp = str(int(time.time()))
delivery_id = "evt_123"
digest = hmac.new(
    secret.encode(),
    timestamp.encode() + b"." + delivery_id.encode() + b"." + body,
    hashlib.sha256,
).hexdigest()
```

GitHub uses `X-Hub-Signature-256`, `X-GitHub-Delivery`, and `X-GitHub-Event`. Because GitHub's
standard signature covers the body but not the delivery header, the receiver also treats an
identical authenticated GitHub body digest as a replay even if the delivery header changes. A
verified GitHub `ping` returns `pong` without creating document work.

## Management API

All `/v1/deliveries/...` endpoints require `Authorization: Bearer <MANAGEMENT_TOKEN>`.
The webhook secrets cannot be used as management credentials.

```text
GET  /v1/deliveries/{id}
GET  /v1/deliveries/{id}/transitions
GET  /v1/deliveries/{id}/changes
POST /v1/deliveries/{id}/decisions
POST /v1/deliveries/{id}/retry
GET  /v1/deliveries/{id}/artifact
```

Decisions may be submitted in partial batches. Export cannot begin until every proposed change
has an approve/reject decision. Manual retry accepts failed jobs only; active jobs are rejected,
and `needs_attention` requires external-state reconciliation before any retry.

## Tests

Use Python 3.12, matching the container:

```bash
uv sync --python 3.12 --extra dev
uv run --python 3.12 python -m pytest tests --ignore=tests/integration
```

Integration tests require a disposable PostgreSQL database:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/webhook_receiver_test \
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/webhook_receiver_test \
SUPERDOCS_API_KEY=test \
WEBHOOK_SECRET=ssssssssssssssssssssssssssssssss \
GITHUB_WEBHOOK_SECRET=gggggggggggggggggggggggggggggggg \
MANAGEMENT_TOKEN=mmmmmmmmmmmmmmmmmmmmmmmmmmmmmmmm \
uv run --python 3.12 python -m pytest tests/integration
```

CI uses deterministic fake SuperDocs processors for workflow proofs and mocked HTTP boundary
tests for the documented API exchange, so it does not consume model operations. Before a real
release, run the bootstrap and one opt-in live workflow against the intended SuperDocs account.

## Security and operational limits

- Authentication happens over exact bytes before JSON parsing.
- Only route-allowlisted payload fields become durable worker input.
- Full payloads, raw signatures, and secrets are not stored or logged.
- No event-controlled URL, local path, credential, or document ID is accepted.
- Exported artifacts are capped at 10 MiB and require management authentication.
- The container runs as a non-root user.
- PostgreSQL artifact storage is a bounded reference adapter, not unlimited object storage.
- Template-list response parsing is deliberately strict; a changed upstream shape stops setup
  rather than creating duplicate templates.
- The management surface is bearer-token protected; webhook ingress intentionally uses provider
  signatures rather than user authentication. Put the public service behind host-level rate
  limiting/WAF rules. Local Compose exposes the web port on loopback only.
- `SUPERDOCS_BASE_URL` must use HTTPS except for loopback development, preventing API keys from
  being sent to a plaintext remote endpoint.

## Screenshot

![Webhook receiver overview](docs/webhook-receiver-overview.png)

Built this for the SuperDocs task.

## Deployment status

`render.yaml` provisions a Starter web service, Starter worker, and `basic-256mb` PostgreSQL 18
database. Its pre-deploy command runs migrations and template bootstrap. The Blueprint is
implemented but has not been deployed from a fresh public standalone repository in this
workspace, because no Render account, production key, or canonical remote was provided.

## References

- [SuperDocs server integration](https://docs.superdocs.app/guides/server-integration)
- [SuperDocs async jobs](https://docs.superdocs.app/guides/async-jobs)
- [SuperDocs human-in-the-loop](https://docs.superdocs.app/guides/human-in-the-loop)
- [SuperDocs templates](https://docs.superdocs.app/concepts/templates)
- [SuperDocs durable Files](https://docs.superdocs.app/concepts/files)
- [GitHub webhook validation](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries)
- [Render Blueprint specification](https://render.com/docs/blueprint-spec)
