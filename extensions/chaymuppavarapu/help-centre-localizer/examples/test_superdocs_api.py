import json
import os
import uuid

import requests


BASE_URL = "https://api.superdocs.app"


def main():
    api_key = os.getenv("SUPERDOCS_API_KEY")

    if not api_key:
        raise RuntimeError(
            "SUPERDOCS_API_KEY is not set."
        )

    paragraphs = [
        "Open SuperDocs from your workspace.",
        "Select Create Project from the dashboard.",
        "Press Ctrl + K to open the project command menu.",
        "Enter the project name and select Create.",
        "Run npm install before starting the application.",
    ]

    for index, text in enumerate(paragraphs):
        print()
        print("=" * 70)
        print(f"PARAGRAPH {index}")
        print("=" * 70)

        message = f"""
Translate this help-centre content into Spanish.

This is a localization task.

You MUST translate every human-readable sentence and UI label.

Rules:
1. Translate the English sentence into Spanish.
2. Keep "SuperDocs" unchanged.
3. Keep "Ctrl + K" unchanged.
4. Keep "npm install" unchanged.
5. Do not return the original English sentence.
6. Return only the localized content.

Content:
{text}
""".strip()

        payload = {
            "message": message,
            "session_id": f"debug-localizer-{uuid.uuid4()}",
            "document_html": text,
            "approval_mode": "approve_all",
        }

        try:
            response = requests.post(
                f"{BASE_URL}/v1/chat",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=120,
            )

            print(f"HTTP STATUS: {response.status_code}")

            response.raise_for_status()

            data = response.json()

            print("\nRAW API RESPONSE:")
            print(
                json.dumps(
                    data,
                    indent=2,
                    ensure_ascii=False,
                )
            )

        except Exception as exc:
            print(f"\nERROR: {exc}")


if __name__ == "__main__":
    main()