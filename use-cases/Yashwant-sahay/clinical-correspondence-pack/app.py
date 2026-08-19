import json
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv()

SUPERDOCS_API_KEY = os.getenv("SUPERDOCS_API_KEY")
SUPERDOCS_MCP_URL = os.getenv(
    "SUPERDOCS_MCP_URL",
    "https://api.superdocs.app/mcp/",
)


def load_encounter() -> dict:
    """Load the fabricated encounter record."""
    path = Path(__file__).parent / "synthetic_encounter.json"

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def check_configuration() -> None:
    """Fail early if the required configuration is missing."""
    if not SUPERDOCS_API_KEY:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is missing. "
            "Add it to the local .env file."
        )


def superdocs_request(payload: dict) -> dict:
    """
    Send a JSON request to the SuperDocs MCP endpoint.

    The API key is read only from the local environment and is
    never printed or returned.
    """
    check_configuration()

    response = requests.post(
        SUPERDOCS_MCP_URL,
        headers={
            "Authorization": f"Bearer {SUPERDOCS_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json=payload,
        timeout=60,
    )

    response.raise_for_status()

    try:
        return response.json()
    except ValueError:
        return {
            "status_code": response.status_code,
            "text": response.text,
        }


def main() -> None:
    encounter = load_encounter()

    print("Clinical Correspondence Pack")
    print("--------------------------------")
    print("Fabricated encounter loaded successfully.")
    print(f"Patient: {encounter['patient']['name']}")
    print(f"Record ID: {encounter['patient']['record_id']}")
    print(f"Encounter: {encounter['encounter']['date']}")
    print()
    print(
        "No real patient information is used by this demonstration."
    )


if __name__ == "__main__":
    main()