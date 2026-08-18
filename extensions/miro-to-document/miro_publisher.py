import os

import requests
from dotenv import load_dotenv


load_dotenv()


def publish_document_link(document_url):
    """
    Add a document link back onto the configured Miro board.
    """

    token = os.getenv("MIRO_ACCESS_TOKEN")
    board_id = os.getenv("MIRO_BOARD_ID")

    if not token:
        raise RuntimeError(
            "MIRO_ACCESS_TOKEN is missing"
        )

    if not board_id:
        raise RuntimeError(
            "MIRO_BOARD_ID is missing"
        )

    # Miro text item creation endpoint
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
            "content": (
                "<p>📄 "
                "Miro Workshop Document Generated"
                "</p>"
                f"<p>"
                f"<a href=\"{document_url}\">"
                "View generated document"
                "</a>"
                "</p>"
            )
        },
        "position": {
            "x": 0,
            "y": 0
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
            "Failed to publish document link to Miro: "
            f"{response.status_code} - "
            f"{response.text}"
        )

    result = response.json()

    print(
        "Document link successfully added to Miro!"
    )

    print(
        f"Miro item ID: {result.get('id')}"
    )

    return result


if __name__ == "__main__":

    document_url = os.getenv(
        "DOCUMENT_PUBLIC_URL"
    )

    if not document_url:
        raise RuntimeError(
            "DOCUMENT_PUBLIC_URL is missing"
        )

    publish_document_link(
        document_url
    )