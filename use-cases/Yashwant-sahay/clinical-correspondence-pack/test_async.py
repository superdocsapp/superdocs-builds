import json
import os
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("SUPERDOCS_API_KEY")
MCP_URL = os.getenv(
    "SUPERDOCS_MCP_URL",
    "https://api.superdocs.app/mcp/",
)

SESSION_ID = "clinical-correspondence-async-demo"


def mcp_request(request_id, method, params=None):

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }

    if params is not None:
        payload["params"] = params

    response = requests.post(
        MCP_URL,
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    return response.json()


def call_tool(request_id, name, arguments):

    return mcp_request(
        request_id,
        "tools/call",
        {
            "name": name,
            "arguments": arguments,
        },
    )


def main():

    with open(
        "synthetic_encounter.json",
        "r",
        encoding="utf-8",
    ) as file:
        encounter = json.load(file)

    prompt = """
Create a Clinical Correspondence Pack from this synthetic encounter.

Create exactly four sections:

1. Referral Letter
2. Discharge Summary
3. Results Letter to Patient
4. Prior-Authorisation Letter

Use ONLY information contained in the supplied record.

Do not invent clinical information.

The referral must be to Cardiology.

The discharge summary must describe an outpatient follow-up,
not a hospitalization.

The results letter must use plain language.

The prior-authorisation letter must use only the supplied insurance
information.

Clearly identify the record as fabricated demonstration data.

The clinician signature must remain pending human approval.

SOURCE RECORD:

""" + json.dumps(
        encounter,
        indent=2,
        ensure_ascii=False,
    )

    response = call_tool(
        1,
        "chat_async",
        {
            "message": prompt,
            "session_id": SESSION_ID,
            "approval_mode": "ask_every_time",
            "model_tier": "pro",
            "thinking_depth": "deep",
        },
    )

    print(
        json.dumps(
            response,
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()