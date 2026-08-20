# SuperDocs M1 bug report: proposal targets cannot be reconciled

## Classification

`BLOCKED_REAL_DEFECT` — a provider proposal-to-chunk correlation discrepancy.
LineCard's M1 review flow correctly blocks rather than guessing which
safety-critical section a proposed edit would affect.

## Corrected evidence

An initial investigation read only `html` / `document_html` from
`document_sync`. The documented prepared HTML is in `document_sync.content`,
so that initial observation is superseded and is not used as provider evidence.

After correcting the parser, two bounded checks used the authoritative prepared
HTML and both found no direct proposal ownership:

| Observation | Synchronized chunks | Proposal targets | Direct intersection | Approval/export |
|---|---:|---:|---:|---|
| Read-only recovery of an existing awaiting-approval job | 8 | 6 | 0 | none / none |
| Fresh capped live M1 operation | 8 | 31 | 0 | none / none |

The fresh run consumed exactly one AI operation, reached `awaiting_approval`,
and submitted no decision or export request. Thus request creation, streaming,
and the review boundary function; direct target correlation does not.

## Expected contract

1. `document_sync.content` contains prepared HTML with `data-chunk-id` target
   identifiers.
2. Every edit proposal in `proposed_change_batch` or
   `metadata.pending_changes` references one such identifier via `chunk_id`.
3. The client then verifies document identity, prior content, version,
   evidence rules, and an explicit reviewer decision before approval.

## Safe reproduction

1. Send a staging document with `approval_mode=ask_every_time`.
2. Wait for `awaiting_approval`.
3. Parse the job's `document_sync.content` as the authoritative prepared HTML.
4. Compare its complete set of `data-chunk-id` values with proposal
   `chunk_id` values.
5. If any proposal has no direct owner, submit no approval and do not export.

## Required provider resolution

Provide either proposal `chunk_id` values that match synchronized
`data-chunk-id` values, or an explicit immutable correlation field from each
proposal to its synchronized chunk. Heading/text similarity is not a safe
substitute for an operator-card review flow.

## Public-safety boundary

Only counts and SHA-256 fingerprints are retained. This repository excludes
API keys, sessions, document/job/change IDs, signed URLs, raw chunk IDs, and
raw provider payloads.
