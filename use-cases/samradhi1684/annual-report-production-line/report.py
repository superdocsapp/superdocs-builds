import os
import requests

from workflow import load_state


API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
}


def get_documents(session_id):
    response = requests.get(
        f"{BASE_URL}/v1/sessions/{session_id}/documents",
        headers=HEADERS,
        timeout=60,
    )

    response.raise_for_status()

    return response.json().get("documents", [])


def show_report_status():

    state = load_state()

    print("\n" + "=" * 70)
    print(state["report_title"])
    print("DOCUMENT + REVIEW STATUS")
    print("=" * 70)

    for section, information in state["documents"].items():

        document_id = information["document_id"]
        filename = information["filename"]
        stage = information["stage"]

        document_name = filename.removesuffix(".html")

        print(f"\n{section}")
        print(f"  SuperDocs document: {document_name}")
        print(f"  Document ID:        {document_id}")
        print(f"  Review stage:       {stage}")

    print("\n" + "=" * 70)

if __name__ == "__main__":
    show_report_status()