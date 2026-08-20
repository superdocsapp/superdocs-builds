"""
check_export_formats.py — asks Canva directly what export formats
this specific design actually supports, instead of guessing.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import json
import requests

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]
#DESIGN_ID = "DAHSiXKMgD4"
DESIGN_ID = "DAHSibxC5DE"  # Outdoor-Inspired Flyer with Hand-Crafted Design

response = requests.get(
    f"https://api.canva.com/rest/v1/designs/{DESIGN_ID}/export-formats",
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
)

print(f"Status: {response.status_code}")
print(json.dumps(response.json(), indent=2))