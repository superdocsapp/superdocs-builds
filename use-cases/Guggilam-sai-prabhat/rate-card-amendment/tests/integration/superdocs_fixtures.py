"""Recorded SuperDocs MCP response bodies, captured from live API calls made
during development (session smoketest-001 against
fixtures/contracts/contract_01_northstar.md). Used to build deterministic
`httpx.MockTransport` responses so the integration tests never touch the
network or consume SuperDocs quota.
"""

from __future__ import annotations

import json

UPLOAD_DOCUMENT_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "html": None,
                        "session_id": "smoketest-001",
                        "filename": "contract_01_northstar.md",
                        "chunks_count": 34,
                        "version_id": "a3b1e163-c48d-497c-82b9-39f916751ccf",
                        "page_setup": None,
                        "persisted": True,
                    }
                ),
            }
        ],
        "isError": False,
    },
}

CHAT_ASYNC_QUEUED_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "job_id": "3585ccfb-9281-4071-901c-af64f80eabc6",
                        "session_id": "smoketest-001",
                        "status": "pending",
                        "message": "Chat request queued for processing",
                    }
                ),
            }
        ],
        "isError": False,
    },
}

_PENDING_CHANGE = {
    "change_id": "41c3fc53-b2f7-4bea-b887-aa05f76a80ea",
    "operation": "create",
    "chunk_id": "new",
    "document_id": "doc_primary",
    "old_html": None,
    "new_html": (
        '<h2 style="color: #1f3a5f;">Schedule A — Rate Card</h2>'
        '<table style="width: 100%; border-collapse: collapse; border: 1px solid #d0d7de;">'
        "<thead><tr><th>Destination</th><th>Prefix</th><th>Rate (USD/min)</th></tr></thead>"
        "<tbody>"
        "<tr><td>United States</td><td>1</td><td>0.0039</td></tr>"
        "<tr><td>United Kingdom</td><td>44</td><td>0.0061</td></tr>"
        "<tr><td>Germany</td><td>49</td><td>0.0064</td></tr>"
        "</tbody></table>"
    ),
    "ai_explanation": (
        "✅ I have added the 'Schedule A — Rate Card' table immediately "
        "after Article 1, ensuring all other clauses and sections remain unchanged."
    ),
}

GET_JOB_AWAITING_APPROVAL_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "job_id": "3585ccfb-9281-4071-901c-af64f80eabc6",
                        "organization_id": None,
                        "user_id": "c4d98af2-99e7-4391-8c6f-6b2ccb6ddc25",
                        "session_id": "smoketest-001",
                        "job_type": "chat",
                        "status": "awaiting_approval",
                        "created_at": "2026-08-06T06:51:36.246718",
                        "updated_at": "2026-08-06T06:51:54.860194",
                        "progress": 90,
                        "result": None,
                        "error": None,
                        "metadata": {
                            "pending_changes": [_PENDING_CHANGE],
                            "cumulative_tokens": 251300,
                        },
                    }
                ),
            }
        ],
        "isError": False,
    },
}

GET_JOB_COMPACT_AWAITING_APPROVAL_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "job_id": "3585ccfb-9281-4071-901c-af64f80eabc6",
                        "status": "awaiting_approval",
                        "progress": 90,
                        "result": None,
                        "error": None,
                        "metadata": {"pending_changes": None},
                    }
                ),
            }
        ],
        "isError": False,
    },
}

APPROVE_CHANGE_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 4,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps({"status": "ok", "message": "Approval processed", "batch_complete": True}),
            }
        ],
        "isError": False,
    },
}

_EXPORTED_MARKDOWN = """# INTERCONNECTION AND WHOLESALE VOICE TERMINATION AGREEMENT

**Agreement No.:** NSC-IX-2021-0447

**Parties:** Northstar Wholesale Carrier Services, Inc. ("Northstar") and Meridian Global Transit Ltd. ("Meridian")

**Effective Date:** March 1, 2021

---

## Article 1 — Definitions

1.1 "Services" means the origination, transit, and termination of wholesale voice traffic between the Parties' networks as further described in Schedule A.

1.2 "Rate Card" means the then-current schedule of per-minute rates attached as Schedule A, as may be amended under Article 7.

1.3 "Effective Date" means the date first written above.

## Schedule A — Rate Card

| Destination | Prefix | Rate (USD/min) |
| --- | --- | --- |
| United States | 1 | 0.0039 |
| United Kingdom | 44 | 0.0061 |
| Germany | 49 | 0.0064 |

## Article 2 — Term

2.1 This Agreement commences on the Effective Date and continues for an initial term of twenty-four (24) months, renewing automatically thereafter for successive twelve (12) month periods unless terminated per Article 9.

## Article 4 — Rates and Billing

4.1 Rates for the Services are set forth in the Rate Card attached as Schedule A, effective as of the Effective Date.

## Article 7 — Rate Amendments

7.1 Either Party may propose an amendment to the Rate Card by delivering written notice to the other Party at least **thirty (30) calendar days** prior to the proposed effective date of the new rates.
"""

EXPORT_DOCUMENT_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 5,
    "result": {"content": [{"type": "text", "text": _EXPORTED_MARKDOWN}], "isError": False},
}

MALFORMED_INNER_JSON_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 6,
    "result": {
        "content": [{"type": "text", "text": '{"job_id": "abc", "status": "awaiting_approval", "metadata": {'}],
        "isError": False,
    },
}

JOB_NOT_FOUND_IS_ERROR_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 8,
    "result": {
        "content": [{"type": "text", "text": "Error calling tool 'get_job': HTTP error 404: Not Found - {'detail': 'Job not found'}"}],
        "isError": True,
    },
}

ACCOUNT_STATUS_ENVELOPE = {
    "jsonrpc": "2.0",
    "id": 7,
    "result": {
        "content": [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "account_id": "c4d98af2-99e7-4391-8c6f-6b2ccb6ddc25",
                        "tier": "free",
                        "quota": {"tier": "free", "monthly_limit": 500, "used": 0, "remaining": 500},
                        "is_agent_account": False,
                    }
                ),
            }
        ],
        "isError": False,
    },
}
