"""
canva_pipeline.py — reusable Canva-side functions for the Streamlit
app. Wraps the same export/download/extract logic already verified
working in download_design_assets.py, as real functions instead of a
top-to-bottom script, so the UI can call them on button clicks.
"""
import time
from pathlib import Path

import requests

CANVA_API_BASE = "https://api.canva.com/rest/v1"
PRINT_WIDTH_PX = 2480
PRINT_HEIGHT_PX = 3508


def list_designs(access_token: str) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{CANVA_API_BASE}/designs", headers=headers)
    if response.status_code != 200:
        return []
    return response.json().get("items", [])

def create_export(access_token: str, design_id: str, format_type: str, extra: dict = None) -> tuple:
    """Returns (job_id, error_detail). job_id is None on failure, with
    error_detail holding the real API response so callers can show it."""
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {"design_id": design_id, "format": {"type": format_type, **(extra or {})}}
    response = requests.post(f"{CANVA_API_BASE}/exports", headers=headers, json=body)
    data = response.json()
    job = data.get("job", {})
    if job.get("id"):
        return job["id"], None
    return None, data

def poll_export(access_token: str, export_id: str, max_attempts: int = 30) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    for _ in range(max_attempts):
        response = requests.get(f"{CANVA_API_BASE}/exports/{export_id}", headers=headers)
        data = response.json()
        status = data.get("job", {}).get("status")
        if status == "success":
            return data["job"]["urls"]
        if status == "failed":
            return []
        time.sleep(2)
    return []

def pull_design_assets(access_token: str, design_id: str, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"pdf_path": None, "png_path": None, "errors": []}

    pdf_job, pdf_error = create_export(access_token, design_id, "pdf")
    if pdf_error:
        result["errors"].append(f"PDF export failed: {pdf_error}")
    elif pdf_job:
        pdf_urls = poll_export(access_token, pdf_job)
        if pdf_urls:
            pdf_path = output_dir / "page_1.pdf"
            pdf_path.write_bytes(requests.get(pdf_urls[0]).content)
            result["pdf_path"] = pdf_path

    orientation = get_design_orientation(access_token, design_id)
    if orientation == "landscape":
        png_width, png_height = PRINT_HEIGHT_PX, PRINT_WIDTH_PX
    else:
        png_width, png_height = PRINT_WIDTH_PX, PRINT_HEIGHT_PX

    png_job, png_error = create_export(access_token, design_id, "png", {"width": png_width, "height": png_height})
    if png_error:
        result["errors"].append(f"PNG export failed: {png_error}")
    elif png_job:
        png_urls = poll_export(access_token, png_job)
        if png_urls:
            png_path = output_dir / "page_1.png"
            png_path.write_bytes(requests.get(png_urls[0]).content)
            result["png_path"] = png_path

    return result

def get_user_info(access_token: str) -> dict:
    """GET /v1/users/me — returns user_id and team_id, no special
    scope required. Used to show which Canva account is connected."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{CANVA_API_BASE}/users/me", headers=headers)
    if response.status_code != 200:
        return {}
    data = response.json()
    team_user = data.get("team_user", {})
    return {"user_id": team_user.get("user_id"), "team_id": team_user.get("team_id")}

def get_design_orientation(access_token: str, design_id: str) -> str:
    """Returns 'portrait' or 'landscape' based on the design's own
    thumbnail dimensions - real proof of orientation, not assumed."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{CANVA_API_BASE}/designs/{design_id}", headers=headers)
    if response.status_code != 200:
        return "portrait"  # safe fallback
    thumb = response.json().get("design", {}).get("thumbnail", {})
    width, height = thumb.get("width", 0), thumb.get("height", 0)
    return "landscape" if width > height else "portrait"