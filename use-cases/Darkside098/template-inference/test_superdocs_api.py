import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("SUPERDOCS_API_KEY")

if not api_key:
    raise RuntimeError("SUPERDOCS_API_KEY was not found in .env")

response = requests.get(
    "https://api.superdocs.app/v1/sessions",
    headers={
        "Authorization": f"Bearer {api_key}",
    },
    timeout=30,
)

print(f"HTTP status: {response.status_code}")

if response.ok:
    print("SuperDocs API connection successful!")
    print(response.text[:500])
else:
    print("SuperDocs API request failed.")
    print(response.text[:500])