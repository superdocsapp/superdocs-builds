"""
test_chat.py — the mandatory "one small instruction first" step from
the brief, done deliberately: a single real edit on a tiny throwaway
document, so we see the API's actual behavior (including possible
first-call slowness) before building anything real on top of it.
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
        "message": "Add a one-sentence summary at the top",
        "session_id": "canva-app-warmup-test",
        "document_html": "<h1>Test Document</h1><p>This is a test paragraph for the Canva app build.</p>",
    },
)

print(f"Status code: {response.status_code}")
print(f"Response:\n{response.text[:2000]}")