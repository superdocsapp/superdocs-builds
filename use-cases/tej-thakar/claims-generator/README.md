# Insurance Claims Correspondence Generator

Generates insurance claim letters (approval, partial approval, denial, information request) from structured claim data using SuperDocs with explicit HITL review. No letter is finalised without an explicit `POST /approve/{session_id}` call.

## Letter types

- `approval` — payout confirmed, amount stated
- `partial_approval` — partial payout with reason for difference
- `denial` — denied with policy exclusion cited, appeal rights noted
- `information_request` — lists required documents with 14-day deadline

## Usage

```bash
pip install -r requirements.txt
cp .env.example .env   # fill in SUPERDOCS_API_KEY
uvicorn main:app --port 8011
```

## API

**`POST /generate`** — start generation for a single letter

```json
{
  "claimant": {
    "full_name": "Priya Sharma",
    "address": "14 Maple Grove, Pune 411001",
    "email": "priya@example.com"
  },
  "policy": {
    "policy_number": "POL-789-XYZ",
    "coverage_limit": 50000,
    "deductible": 5000,
    "coverage_type": "homeowner"
  },
  "claim": {
    "claim_number": "CLM-2026-0042",
    "incident_date": "2026-07-15",
    "incident_type": "water damage",
    "claimed_amount": 45000,
    "adjuster_estimate": 38500,
    "adjuster_notes": "Flooring measurement discrepancy"
  },
  "letter_type": "partial_approval",
  "company_name": "InSureCo Insurance Ltd."
}
```

When SuperDocs reaches the human-review gate, returns:

```json
{
  "claim_number": "CLM-2026-0042",
  "letter_type": "partial_approval",
  "letter_html": null,
  "letter_text": null,
  "session_id": "claim-CLM-2026-0042-a1b2c3d4",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending_hitl"
}
```

The draft is sitting in SuperDocs awaiting a human decision. Nothing has been applied to the document yet. A reviewer must explicitly approve:

**`POST /approve/{session_id}`**

```json
{ "approved": true }
```

The service calls SuperDocs with the stored `job_id` and `change_id` list, waits for completion, exports the letter, and returns:

```json
{
  "claim_number": "CLM-2026-0042",
  "letter_type": "partial_approval",
  "letter_html": "<html>...</html>",
  "letter_text": "Dear Ms. Sharma, ...",
  "session_id": "claim-CLM-2026-0042-a1b2c3d4",
  "status": "approved"
}
```

To reject instead:

**`POST /reject/{session_id}`**

```json
{ "approved": false, "reason": "Coverage reasoning needs adjustment" }
```

The `reason` is sent to SuperDocs as per-change feedback so the AI can revise if the session is restarted.

To inspect a session without touching it:

**`GET /status/{session_id}`**

Returns one of: `processing`, `pending_hitl`, `approved`, `error`.

**`POST /generate/batch`** — up to 20 letters at once. Each letter sits independently in HITL approval; the batch response may contain a mix of `pending_hitl`, `approved`, and `error` statuses.

## SuperDocs flow (per letter)

1. `POST /v1/chat/async` — send claim record as `document_html`, letter instruction as `message`, `approval_mode: ask_every_time`
2. `GET /v1/jobs/{job_id}` — poll until `awaiting_approval` (HITL gate) or `completed`
3. Return `pending_hitl` — session state (`job_id`, `pending_changes`) stored server-side
4. Human calls `POST /approve/{session_id}` → service calls `POST /v1/chat/{session_id}/approve` with `job_id` + `change_id` list
5. `POST /v1/documents/export` — export the final letter as HTML

## Notes

- Session state is held in-memory; a process restart drops pending sessions. Use Redis or a database in production.
- 5-minute timeout per letter; HITL sessions are cleaned up by SuperDocs after ~1 hour if not approved.
