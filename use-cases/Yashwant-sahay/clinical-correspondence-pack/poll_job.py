import json
import os
import time
import requests
from dotenv import load_dotenv


load_dotenv()

API_KEY = os.getenv("SUPERDOCS_API_KEY")
MCP_URL = os.getenv(
    "SUPERDOCS_MCP_URL",
    "https://api.superdocs.app/mcp/",
)

SESSION_ID = "clinical-correspondence-async-demo"
JOB_ID = "cf5483c3-87ae-47b5-a317-42343b3e8517"


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


def extract_result(response):

    result = response.get("result", {})

    if "structuredContent" in result:
        return result["structuredContent"]

    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item["text"])
            except json.JSONDecodeError:
                pass

    return result


def main():

    print("Polling SuperDocs job...")
    print(f"Job ID: {JOB_ID}")

    for attempt in range(1, 31):

        response = call_tool(
            attempt,
            "get_job",
            {
                "session_id": SESSION_ID,
                "job_id": JOB_ID,
            },
        )

        result = extract_result(response)

        print()
        print("=" * 80)
        print(f"ATTEMPT {attempt}")
        print("=" * 80)
        print(
            json.dumps(
                result,
                indent=2,
                ensure_ascii=False,
            )
        )

        status = result.get("status")

        if status in {
            "awaiting_approval",
            "completed",
            "failed",
            "cancelled",
        }:
            print()
            print(f"FINAL STATUS: {status}")
            return

        time.sleep(3)

    print()
    print("Polling timed out after 90 seconds.")


if __name__ == "__main__":
    main()