"""
test_template_usage.py — the real test: does SuperDocs' AI actually
reference our uploaded template when drafting new content, or does it
just sit there unused? A completely FRESH session, with a request
that only succeeds correctly if the AI pulled from the template
(since we never tell it the colors directly this time).
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

response = requests.post(
    "https://api.superdocs.app/v1/chat",
    headers=HEADERS,
    json={
        "message": (
            "Draft a one-paragraph product announcement for a new ROOTED Cold Brew "
            "flavor, using my ROOTED brand template for the visual style."
        ),
        "session_id": "template-usage-test",
    },
)

print(f"Status: {response.status_code}")
data = response.json()
print(f"\nAI response: {data.get('response')}")
print(f"\nGenerated HTML:\n{data.get('document_changes', {}).get('updated_html')}")