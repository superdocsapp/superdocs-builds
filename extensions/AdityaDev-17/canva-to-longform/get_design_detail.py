"""
get_design_detail.py — pulls full metadata for multiple designs and
prints them side by side, so we can compare exactly what differs
between a design that pulls successfully and one that returns
permission_denied on export.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import json
import requests

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]

DESIGNS_TO_CHECK = {
    "ROOTED (works)": "DAHSiXKMgD4",
    "Outdoor-Inspired (fails)": "DAHSibxC5DE",
}

for label, design_id in DESIGNS_TO_CHECK.items():
    print(f"=== {label} — {design_id} ===")
    response = requests.get(
        f"https://api.canva.com/rest/v1/designs/{design_id}",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )
    print(f"Status: {response.status_code}")
    print(json.dumps(response.json(), indent=2))
    print()