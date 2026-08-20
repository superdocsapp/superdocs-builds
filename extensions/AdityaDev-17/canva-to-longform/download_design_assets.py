"""
download_design_assets.py — requests a PDF export (text + layout) and
a PNG export (visual palette + embeddable image) of the design,
downloads both, and saves them locally.

Print-resolution fix: the default PNG export returned 794x1123 pixels
- confirmed to be exactly A4 at 96 DPI (screen resolution), not print
quality. Now explicitly requesting 2480x3508 (A4 at true 300 DPI,
matching the design's actual proportions rather than forcing US
Letter dimensions onto an A4-shaped design). Verified after download
by checking the actual saved file's pixel dimensions - proof, not
assumption.

Scope decision, logged: Canva's html_bundle export isn't supported for
this design type (confirmed via /export-formats), so PDF is used for
text/layout and PNG for the visual palette instead of one combined
HTML export.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import time
from pathlib import Path

import requests
from PIL import Image

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]
DESIGN_ID = "DAHSiXKMgD4"
HEADERS = {"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"}

OUTPUT_DIR = Path("design_assets") / DESIGN_ID
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# A4 at 300 DPI (true print resolution), matching this design's actual
# proportions (confirmed via the default 794x1123 export = A4 at 96 DPI).
PRINT_WIDTH_PX = 2480
PRINT_HEIGHT_PX = 3508


def create_export(format_type: str, extra: dict | None = None) -> str:
    body = {"design_id": DESIGN_ID, "format": {"type": format_type, **(extra or {})}}
    response = requests.post(
        "https://api.canva.com/rest/v1/exports",
        headers=HEADERS,
        json=body,
    )
    data = response.json()
    job = data.get("job", {})
    if "id" not in job:
        print(f"  export creation failed: {data}")
        return None
    return job["id"]


def poll_export(export_id: str) -> list[str]:
    for _ in range(30):
        response = requests.get(f"https://api.canva.com/rest/v1/exports/{export_id}", headers=HEADERS)
        data = response.json()
        status = data.get("job", {}).get("status")
        if status == "success":
            return data["job"]["urls"]
        if status == "failed":
            print(f"  export failed: {data}")
            return []
        time.sleep(2)
    print("  export timed out after 60s")
    return []


def download(url: str, out_path: Path):
    response = requests.get(url)
    out_path.write_bytes(response.content)
    print(f"  saved {out_path} ({len(response.content):,} bytes)")


print("Requesting PDF export...")
pdf_job_id = create_export("pdf")
if pdf_job_id:
    pdf_urls = poll_export(pdf_job_id)
    for i, url in enumerate(pdf_urls):
        download(url, OUTPUT_DIR / f"page_{i+1}.pdf")

print("\nRequesting PNG export at print resolution (2480x3508, A4 @ 300 DPI)...")
png_job_id = create_export("png", {"width": PRINT_WIDTH_PX, "height": PRINT_HEIGHT_PX})
if png_job_id:
    png_urls = poll_export(png_job_id)
    for i, url in enumerate(png_urls):
        out_path = OUTPUT_DIR / f"page_{i+1}.png"
        download(url, out_path)

        # Verify, don't assume: confirm the actual saved file is really print-res
        actual_size = Image.open(out_path).size
        actual_dpi = round(actual_size[0] / 8.27)  # A4 width in inches
        print(f"  verified actual dimensions: {actual_size} (~{actual_dpi} DPI)")
        if actual_size[0] < 2000:
            print(f"  WARNING: still appears to be screen resolution, not print quality")

print(f"\nAll assets saved to {OUTPUT_DIR}/")