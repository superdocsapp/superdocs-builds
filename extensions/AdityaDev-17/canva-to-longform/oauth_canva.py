"""
oauth_canva.py — one-time OAuth flow to get a Canva access token.

Uses Authorization Code + PKCE (SHA-256), as required by Canva's
Connect API. Spins up a tiny local HTTP server on 127.0.0.1:8080 to
catch the redirect automatically - no manual copy-pasting a code out
of the browser URL bar.

Run this once to get a token; run it again later if the token expires
and you don't want to build refresh-token handling yet.
"""
import base64
import hashlib
import http.server
import secrets
import threading
import urllib.parse
import webbrowser

import requests
from dotenv import load_dotenv
import os

load_dotenv()

CLIENT_ID = os.environ["CANVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["CANVA_CLIENT_SECRET"]
REDIRECT_URI = "http://127.0.0.1:8080/callback"
SCOPES = "asset:read design:content:read design:meta:read profile:read"

_auth_code = {"value": None}


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code["value"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorized. You can close this tab.</h1>")
        else:
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # silence default request logging


def generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("utf-8").rstrip("=")
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")
    return code_verifier, code_challenge


def main():
    code_verifier, code_challenge = generate_pkce_pair()

    auth_url = (
        "https://www.canva.com/api/oauth/authorize"
        f"?code_challenge_method=s256"
        f"&response_type=code"
        f"&client_id={CLIENT_ID}"
        f"&scope={urllib.parse.quote(SCOPES)}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
        f"&code_challenge={code_challenge}"
    )

    server = http.server.HTTPServer(("127.0.0.1", 8080), CallbackHandler)
    server_thread = threading.Thread(target=server.handle_request)
    server_thread.start()

    print("Opening browser for Canva authorization...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    server_thread.join(timeout=120)

    if _auth_code["value"] is None:
        print("No authorization code received (timed out after 120s). Try again.")
        return

    print("Authorization code received. Exchanging for access token...")

    token_response = requests.post(
        "https://api.canva.com/rest/v1/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": _auth_code["value"],
            "code_verifier": code_verifier,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    print(f"Token exchange status: {token_response.status_code}")
    data = token_response.json()

    if token_response.status_code == 200:
        print(f"\nACCESS TOKEN (valid ~4 hours): {data['access_token'][:20]}...")
        print(f"REFRESH TOKEN: {data.get('refresh_token', 'none')[:20]}...")
        # Save to .env manually - never auto-write secrets to disk without you seeing them first
        print("\nCopy these into your .env file:")
        print(f"CANVA_ACCESS_TOKEN={data['access_token']}")
        print(f"CANVA_REFRESH_TOKEN={data.get('refresh_token', '')}")
    else:
        print(f"Error response: {data}")


if __name__ == "__main__":
    main()