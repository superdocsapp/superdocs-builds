# REST transcript — a full negotiation, no human in Slack

Captured by `scripts/capture_rest_transcript.py` against the built-in fake:
no API key, no network. Every body below is verbatim.

### 1. Open a deal (multipart upload)

`POST /deals/upload` -> **200**

Response
```json
{
  "deal_id": "deal_36003f9993",
  "name": "Acme-Globex MSA",
  "superdocs_session_id": "deal_36003f9993",
  "approval_policy": "dual_consent",
  "current_version": "v1",
  "status": "active"
}
```

### 2. Propose an edit

`POST /deals/deal_36003f9993/propose` -> **200**

Request
```json
{
  "side": "vendor",
  "user": "U_VENDOR",
  "instruction": "Cap liability at $50k in the liability section",
  "source_channel_id": "C_SHARED"
}
```

Response
```json
{
  "job_id": "job_0001",
  "state": "awaiting_review",
  "proposals": [
    {
      "id": "prop_4430ffb944",
      "job_id": "job_0001",
      "change_id": "ch_0002",
      "operation": "edit",
      "old_html": "<p>Section 8: Liability. Each party&#x27;s aggregate liability arising out of this Agreement is unlimited and without cap of any kind.</p>",
      "new_html": "<p>Section 8: Liability. In no event shall either party&#x27;s aggregate liability exceed $50000.</p>",
      "ai_explanation": "Capped aggregate liability at $50000, per the negotiation request.",
      "proposed_by_side": "vendor",
      "vendor_decision": null,
      "customer_decision": null,
      "state": "pending"
    }
  ]
}
```

### 3. Propose the identical edit again (idempotency)

`POST /deals/deal_36003f9993/propose` -> **200**

Request
```json
{
  "side": "vendor",
  "user": "U_VENDOR",
  "instruction": "Cap liability at $50k in the liability section",
  "source_channel_id": "C_SHARED"
}
```

Response
```json
{
  "job_id": "job_0001",
  "state": "awaiting_review",
  "proposals": [
    {
      "id": "prop_4430ffb944",
      "job_id": "job_0001",
      "change_id": "ch_0002",
      "operation": "edit",
      "old_html": "<p>Section 8: Liability. Each party&#x27;s aggregate liability arising out of this Agreement is unlimited and without cap of any kind.</p>",
      "new_html": "<p>Section 8: Liability. In no event shall either party&#x27;s aggregate liability exceed $50000.</p>",
      "ai_explanation": "Capped aggregate liability at $50000, per the negotiation request.",
      "proposed_by_side": "vendor",
      "vendor_decision": null,
      "customer_decision": null,
      "state": "pending"
    }
  ]
}
```

> Same `job_id` as call 2. The repeat folded into the existing job instead of starting a second one and billing a second operation.

### 4. Approve as vendor

`POST /deals/deal_36003f9993/proposals/prop_4430ffb944/decide` -> **200**

Request
```json
{
  "side": "vendor",
  "user": "U_VENDOR",
  "approved": true
}
```

Response
```json
{
  "id": "prop_4430ffb944",
  "job_id": "job_0001",
  "change_id": "ch_0002",
  "operation": "edit",
  "old_html": "<p>Section 8: Liability. Each party&#x27;s aggregate liability arising out of this Agreement is unlimited and without cap of any kind.</p>",
  "new_html": "<p>Section 8: Liability. In no event shall either party&#x27;s aggregate liability exceed $50000.</p>",
  "ai_explanation": "Capped aggregate liability at $50000, per the negotiation request.",
  "proposed_by_side": "vendor",
  "vendor_decision": "approved",
  "customer_decision": null,
  "state": "pending"
}
```

### 5. Approve as customer

`POST /deals/deal_36003f9993/proposals/prop_4430ffb944/decide` -> **200**

Request
```json
{
  "side": "customer",
  "user": "U_CUSTOMER",
  "approved": true
}
```

Response
```json
{
  "id": "prop_4430ffb944",
  "job_id": "job_0001",
  "change_id": "ch_0002",
  "operation": "edit",
  "old_html": "<p>Section 8: Liability. Each party&#x27;s aggregate liability arising out of this Agreement is unlimited and without cap of any kind.</p>",
  "new_html": "<p>Section 8: Liability. In no event shall either party&#x27;s aggregate liability exceed $50000.</p>",
  "ai_explanation": "Capped aggregate liability at $50000, per the negotiation request.",
  "proposed_by_side": "vendor",
  "vendor_decision": "approved",
  "customer_decision": "approved",
  "state": "committed"
}
```

> Under `dual_consent` the change commits only after the second approval. One side alone is recorded but does not commit.

### 6. Status

`GET /deals/deal_36003f9993/status` -> **200**

Response
```json
{
  "deal_id": "deal_36003f9993",
  "name": "Acme-Globex MSA",
  "current_version": "v2",
  "version": "v2",
  "approval_policy": "dual_consent",
  "status": "active",
  "pending_proposals": 0
}
```

### 7. Audit trail

`GET /deals/deal_36003f9993/history` -> **200**

Response
```json
{
  "lines": [
    "[2026-08-27T15:03:05+00:00] vendor/U_VENDOR: deal_started (filename=MSA.docx, policy=dual_consent)",
    "[2026-08-27T15:03:05+00:00] vendor/U_VENDOR: propose_started (job_id=job_0001, document=MSA.docx)",
    "[2026-08-27T15:03:05+00:00] system/system: proposals_drafted (job_id=job_0001, count=1)",
    "[2026-08-27T15:03:05+00:00] vendor/U_VENDOR: propose_deduplicated (job_id=job_0001, reason=an identical instruction is already in flight or was just run)",
    "[2026-08-27T15:03:05+00:00] vendor/U_VENDOR: decision_recorded (approved=True)",
    "[2026-08-27T15:03:05+00:00] customer/U_CUSTOMER: decision_recorded (approved=True)",
    "[2026-08-27T15:03:05+00:00] system/system: proposal_resolved (state=committed)",
    "[2026-08-27T15:03:05+00:00] system/system: job_completed (job_id=job_0001, version=v2, superdocs_result=ok)"
  ]
}
```

---

Seven calls, no Slack, no key. The same `NegotiationService` backs both the
Slack app and this surface, so the rules proved here are the rules in Slack.
