"""
refresh_canva_token.py — uses the saved refresh token to get a new
access token without repeating the full browser OAuth flow. Canva
access tokens are short-lived (~4 hours); the refresh token lasts
much longer and is meant for exactly this.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import requests

CLIENT_ID = os.environ["CANVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["CANVA_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["CANVA_REFRESH_TOKEN"]

response = requests.post(
    "https://api.canva.com/rest/v1/oauth/token",
    data={
        "grant_type": "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    },
    headers={"Content-Type": "application/x-www-form-urlencoded"},
)

print(f"Status: {response.status_code}")
data = response.json()

if response.status_code == 200:
    print(f"\nNew ACCESS TOKEN: {data['access_token']}")
    print(f"New REFRESH TOKEN: {data.get('refresh_token', REFRESH_TOKEN)}")
    print("\nUpdate your .env with these new values:")
    print(f"CANVA_ACCESS_TOKEN={data['access_token']}")
    print(f"CANVA_REFRESH_TOKEN={data.get('refresh_token', REFRESH_TOKEN)}")
else:
    print(f"Error: {data}")