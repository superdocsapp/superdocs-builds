import requests
import os
import sys
import json

API_KEY = os.environ["SUPERDOCS_API_KEY"]
SESSION_ID = sys.argv[1] if len(sys.argv) > 1 else "recipe-costing-build1-v3"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

hist = requests.get(
    f"https://api.superdocs.app/v1/sessions/{SESSION_ID}/history",
    headers=HEADERS,
)

print("HTTP STATUS:", hist.status_code)
print()

try:
    data = hist.json()
except Exception:
    print("RAW RESPONSE:")
    print(hist.text)
    sys.exit(1)

print("TOP-LEVEL KEYS:", list(data.keys()))
print()
print("========== FULL HISTORY ==========")
print(json.dumps(data, indent=2, default=str))
print("========== END HISTORY ==========")