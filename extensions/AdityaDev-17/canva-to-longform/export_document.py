"""
export_document.py — exports the finished long-form document (already
sitting in our SuperDocs session from build_longform_document.py) as
real .docx and .pdf files. This is the `export` surface from the
card - the first time we get an actual downloadable file, not just
raw HTML saved locally.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import base64
import json
import requests

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SESSION_ID = "canva-DAHSiXKMgD4"


def export(format_type: str, filename: str):
    response = requests.post(
        "https://api.superdocs.app/v1/documents/export",
        headers=HEADERS,
        json={
            "session_id": SESSION_ID,
            "format": format_type,
            "options": {
                "paper_size": "Letter",
                "margins": "normal",
                "filename": filename,
            },
        },
    )
    print(f"{format_type} export status: {response.status_code}")

    if response.status_code == 200:
        out_path = f"{filename}.{format_type}"
        with open(out_path, "wb") as f:
            f.write(response.content)
        print(f"  saved {out_path} ({len(response.content):,} bytes)")

        warnings = response.headers.get("X-Export-Warnings")
        if warnings:
            decoded = json.loads(base64.b64decode(warnings))
            print(f"  non-fatal warnings: {decoded}")
    else:
        print(f"  error: {response.text}")


export("docx", "ROOTED_leave_behind_report")
export("pdf", "ROOTED_leave_behind_report")