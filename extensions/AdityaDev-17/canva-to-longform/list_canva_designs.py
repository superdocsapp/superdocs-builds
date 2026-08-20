"""
list_canva_designs.py — lists your real Canva designs via the Connect
API, so we can pick one to test the pull pipeline against. Also
serves as the first real proof the OAuth token actually works for API
calls, not just the token exchange itself.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]

response = requests.get(
    "https://api.canva.com/rest/v1/designs",
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
)

print(f"Status code: {response.status_code}")

if response.status_code == 200:
    data = response.json()
    items = data.get("items", [])
    print(f"\nFound {len(items)} design(s):\n")
    for d in items:
        title = d.get("title", "(untitled)")
        design_id = d.get("id")
        design_type = d.get("design_type", {}).get("type", "unknown")
        print(f"  [{design_type}] {title}")
        print(f"    id: {design_id}\n")
else:
    print(f"Error: {response.text}")