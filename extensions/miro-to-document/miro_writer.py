import os
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv()


def get_config():
    """Load Miro configuration from .env."""

    token = os.getenv("MIRO_ACCESS_TOKEN")
    board_id = os.getenv("MIRO_BOARD_ID")

    if not token:
        raise RuntimeError("MIRO_ACCESS_TOKEN is missing")

    if not board_id:
        raise RuntimeError("MIRO_BOARD_ID is missing")

    return token, board_id


def load_generated_document():
    """Load the generated Markdown document."""

    document_path = Path("output/miro_document.md")

    if not document_path.exists():
        raise FileNotFoundError(
            "Generated document not found. "
            "Run document_generator.py first."
        )

    return document_path.read_text(
        encoding="utf-8"
    )


def create_text_item(text, x=0, y=0):
    """Create a text item on the Miro board."""

    token, board_id = get_config()

    url = (
        f"https://api.miro.com/v2/boards/"
        f"{board_id}/texts"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = {
        "data": {
            "content": text
        },
        "position": {
            "x": x,
            "y": y
        }
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=30
    )

    if not response.ok:
        raise RuntimeError(
            f"Failed to create Miro text item: "
            f"{response.status_code} - "
            f"{response.text}"
        )

    return response.json()


def create_document_summary():
    """
    Create a useful summary item on the Miro board
    based on the generated document.
    """

    document = load_generated_document()

    lines = document.splitlines()

    sections = []

    for line in lines:

        if line.startswith("## "):
            sections.append(
                line.replace("## ", "").strip()
            )

    summary = (
        "📄 <strong>Miro Workshop Document</strong>"
        "<br><br>"
        "Generated successfully from the Miro board."
        "<br><br>"
        "<strong>Sections:</strong><br>"
        + "<br>".join(
            f"• {section}"
            for section in sections
        )
        + "<br><br>"
        "Document: output/miro_document.md"
    )

    return summary


if __name__ == "__main__":

    print("Loading generated document...")

    summary = create_document_summary()

    print("Connecting to Miro...")

    result = create_text_item(
        summary,
        x=900,
        y=0
    )

    print()
    print(
        "Document summary successfully written "
        "back to Miro!"
    )

    print(
        "Item ID:",
        result.get("id")
    )