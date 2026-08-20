"""
test_key.py — verifies the SuperDocs API key works, using the
zero-cost endpoint the docs specifically recommend for this
(GET /v1/sessions never spends an operation).
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]

response = requests.get(
    "https://api.superdocs.app/v1/sessions",
    headers={"Authorization": f"Bearer {API_KEY}"},
)

print(f"Status code: {response.status_code}")
print(f"Response body: {response.json()}")

if response.status_code == 200:
    print("\nKEY IS VALID — SuperDocs API is reachable and authenticated.")
elif response.status_code == 401:
    print("\n401 — key is wrong, revoked, or the Authorization header didn't reach the server.")
else:
    print(f"\nUnexpected status {response.status_code} — check the response body above.")