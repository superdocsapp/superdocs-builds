"""Get a Microsoft Graph token via the device-code flow — no client secret needed.

Prereq: register a free Azure app (Azure Portal -> App registrations -> New), add the
delegated permission `Notes.Read`, mark it a public client, and copy its Application
(client) ID. Then:

    CLIENT_ID=<your-app-id> python get_token.py

It prints a code + URL; sign in there; it then prints an access token you export as
GRAPH_TOKEN. (Fastest alternative for a one-off: grab a token from Graph Explorer,
https://developer.microsoft.com/graph/graph-explorer, with the Notes.Read scope.)
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

TENANT = os.getenv("TENANT", "common")
CLIENT_ID = os.getenv("CLIENT_ID")
SCOPE = "Notes.Read offline_access"
AUTH = f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0"


def _post(url, form):
    data = urllib.parse.urlencode(form).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data)) as r:
        return r.status, json.loads(r.read().decode())


def main():
    if not CLIENT_ID:
        sys.exit("Set CLIENT_ID to your Azure app's Application (client) ID.")
    _, dc = _post(f"{AUTH}/devicecode", {"client_id": CLIENT_ID, "scope": SCOPE})
    print("\n1) Go to:", dc["verification_uri"])
    print("2) Enter code:", dc["user_code"], "\nWaiting for you to sign in...\n")
    while True:
        time.sleep(dc.get("interval", 5))
        try:
            _, tok = _post(f"{AUTH}/token", {
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                "client_id": CLIENT_ID, "device_code": dc["device_code"]})
        except urllib.error.HTTPError:
            continue  # authorization_pending
        if "access_token" in tok:
            print("Access token (export it as GRAPH_TOKEN):\n")
            print(tok["access_token"])
            return


if __name__ == "__main__":
    main()
