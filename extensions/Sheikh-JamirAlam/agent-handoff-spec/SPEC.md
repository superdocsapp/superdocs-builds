# Document Agent Handoff Specification

Version 1.0

## 1. Purpose

This specification defines a document-format-independent contract for passing responsibility for a document from one software agent to another. It prevents an agent from acting on the wrong document, editing outside its task, using a stale lifecycle state, or silently changing a forbidden section.

The handoff envelope carries references and permissions. It is not a document transport format, an edit format, an authentication mechanism, or a replacement for the document server's concurrency and approval controls.

## 2. Terms

- **Document server**: the system that stores the document and exposes its durable identifier, current state, and content or section snapshot.
- **Orchestrator**: the coordinator that starts a workflow, invokes agents in a defined order, submits proposed actions to the validator, and applies only accepted changes.
- **Agent**: a specialized worker that receives an envelope, performs only the assigned task, and returns a structured proposed diff plus the next envelope.
- **Validator**: an independent component that checks an envelope and the observable result of an agent action before any change is committed or the next handoff is honored.
- **Section reference**: an opaque logical reference such as a heading ID, chunk ID, table ID, or application-defined path. It is not raw document text.
- **Action diff**: metadata about what an agent proposed or changed. It must include changed section references and may include before/after values only at the agent/document adapter boundary; envelopes and audit traces should not contain raw content.

## 3. Envelope

An envelope is a JSON object with these fields:

| Field                             | Type             | Required | Meaning                                                             |
| --------------------------------- | ---------------- | -------: | ------------------------------------------------------------------- |
| `envelope_version`                | string           |      yes | Protocol version. Version `"1.0"` is defined here.                  |
| `document_id`                     | string           |      yes | Durable document identifier.                                        |
| `assigned_to`                     | string           |      yes | Identifier of the agent authorized to receive and execute the task. |
| `scope`                           | object           |      yes | Positive permission granted to the receiver.                        |
| `scope.action`                    | string           |      yes | Specific operation the receiver may perform.                        |
| `scope.target_sections`           | array of strings |      yes | Logical sections the receiver may change; at least one.             |
| `restrictions`                    | object           |      yes | Explicit prohibitions.                                              |
| `restrictions.forbidden_sections` | array of strings |       no | Sections the receiver must not change. Defaults to empty.           |
| `restrictions.forbidden_actions`  | array of strings |       no | Operations the receiver must not perform. Defaults to empty.        |
| `review_state`                    | enum             |      yes | `draft`, `pending_review`, `approved`, or `rejected`.               |
| `issued_by`                       | string           |      yes | Component or agent that created this envelope.                      |
| `issued_at`                       | timestamp        |      yes | RFC 3339 timestamp with an explicit timezone or UTC offset.         |

Identifiers must be opaque, non-secret strings. In this reference implementation they are limited to letters, numbers, `.`, `_`, `:`, `/`, and `-`, with a maximum length of 256. Instructions and section references are bounded strings; receivers must reject malformed or oversized values.

`scope.target_sections` and `restrictions.forbidden_sections` must not overlap. Unknown JSON fields must be rejected by a strict receiver so that a receiver does not silently ignore semantics it does not understand.

An envelope must never contain API keys, credentials, access tokens, raw document content, full document HTML, or arbitrary model prompts containing secrets.

## 4. Version compatibility

This specification defines envelope version `1.0`. A receiver that does not understand `envelope_version` must reject the handoff with an explicit compatibility error. It must not guess, downgrade, or perform best-effort processing. A receiver must also reject unknown fields unless a future version explicitly defines an extension mechanism.

## 5. Ownership and lifecycle

The component named by `issued_by` creates the envelope. The component named by `assigned_to` is the only agent authorized to receive and execute it. The orchestrator must route the envelope according to `assigned_to`; an agent must reject an envelope assigned to another agent.

The normal reference demonstration is a fixed sequence:

```text
document server → orchestrator → Agent A → Agent B → Agent A → completed
```

The document server is queried before orchestration begins. The demo does not upload a document. The orchestrator creates the initial envelope for Agent A. Each agent proposes its scoped action. The validator checks that action before the agent's successor envelope is honored:

1. The orchestrator issues envelope v1 for Agent A.
2. Agent A returns a proposed diff. The validator checks it. If accepted, Agent A issues the envelope for Agent B.
3. Agent B returns a proposed diff. The validator checks it. If accepted, Agent B issues the envelope for the final Agent A review.
4. Agent A returns the final proposed diff. The validator checks it. If accepted, the workflow is complete and the document may transition to `approved` according to the document server's approval rules.

`draft` and `pending_review` permit proposed mutations. `approved` and `rejected` do not permit further mutation through this workflow. A receiver must compare the envelope's `document_id` and `review_state` with the current document snapshot before acting. A mismatch is a stale or invalid handoff.

The envelope describes authorization; it does not itself commit a document change. The orchestrator applies a diff only after validator acceptance and after confirming that every before-value still matches the current snapshot.

## 6. Agent contract

An agent receives a valid envelope assigned to that agent, the current document identifier and review state, the minimum document sections needed for the task, and optionally a document-server revision token.

It returns its execution identity, a structured proposed diff, the sections changed, and a successor envelope created only after its proposal has passed validation.

An agent may use an LLM, deterministic code, or both. If an LLM is used, its output must be parsed into a strict structured model. The LLM must not decide its own permissions, target sections, lifecycle transitions, or recipient. Those are enforced by the envelope, agent boundary, validator, and orchestrator.

A proposed change should contain a section reference, a before value, and an after value. The before value must match the current snapshot. An empty diff is valid when the agent inspected its assigned scope and found nothing to change.

## 7. Validator contract

The validator is independent of the agents it evaluates. Given an envelope and an action diff, it must reject when the envelope is malformed or unsupported; the action document ID differs; the receiver differs from `assigned_to`; the lifecycle is `approved` or `rejected`; a changed section is outside scope or forbidden; the action is forbidden; the action differs from `scope.action`; or the document snapshot/revision is stale when revision data is available.

The validator returns an acceptance boolean and a human-readable reason. A rejection must prevent both document commit and successor-envelope processing. Validator input and audit output should contain metadata and section references, not unnecessary raw document content.

## 8. Document-server integration

The protocol is compatible with any document server. An adapter translates server-specific data into an agent-neutral snapshot:

```text
fetch document → DocumentState(document_id, review_state, sections, revision)
```

For the reference SuperDocs demo, the fetch-only adapter calls `GET /v1/documents/{document_id}` with `include_html=true`. It uses a Bearer API key and does not upload or mutate the document. A section extractor maps returned HTML or server chunk structure to logical section references.

Writing accepted changes back to a server is intentionally outside this demo adapter. A production integration must use the server's supported edit, approval, concurrency, and export APIs, and preserve the durable document identity.

## 9. Security and audit requirements

- Keep credentials in environment variables or a secret manager.
- Never put credentials, raw document bodies, or model secrets in envelopes.
- Do not log raw before/after content unless a separately authorized audit policy requires it.
- Record document ID, envelope version, issuer, receiver, lifecycle state, changed section references, validator decision, and reason.
- Treat model output as untrusted input and validate it before application.
- Use least-privilege document-server credentials and enforce server-side authorization independently of this protocol.

## 10. Worked envelope

```json
{
  "envelope_version": "1.0",
  "document_id": "doc_7f3a",
  "assigned_to": "agent-spelling",
  "scope": {
    "action": "review spelling",
    "target_sections": ["section:executive-summary"]
  },
  "restrictions": {
    "forbidden_sections": ["section:financials"],
    "forbidden_actions": ["change figures", "rewrite conclusions"]
  },
  "review_state": "pending_review",
  "issued_by": "orchestrator",
  "issued_at": "2026-08-24T12:00:00Z"
}
```

This example contains references and instructions only. Actual paragraph text and proposed replacements belong in the document adapter/action layer, not in the envelope.
