"""
build_longform_document.py — the real pipeline: takes the extracted
Canva copy + palette + image, uploads the image to SuperDocs, seeds a
session with the copy as real HTML, then instructs the AI to expand
it into a long-form leave-behind document, referencing the uploaded
image and the extracted brand colors explicitly.
"""
import base64
import re
import html
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import os
import requests

from extract_content import extract_text, extract_palette

DESIGN_ID = "DAHSiXKMgD4"
ASSET_DIR = Path("design_assets") / DESIGN_ID
API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
SESSION_ID = f"canva-{DESIGN_ID}"


def convert_markdown_links_to_html(text: str) -> str:
    pattern = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def replacer(match):
        link_text, url = match.group(1), match.group(2)
        return f'<a href="{html.escape(url)}">{html.escape(link_text)}</a>'

    return pattern.sub(replacer, text)


def build_seed_html(text: str) -> str:
    converted = convert_markdown_links_to_html(text)
    lines = [line for line in converted.split("\n") if line.strip()]
    return "\n".join(f"<p>{line}</p>" for line in lines)


def upload_image_to_superdocs(png_path: Path) -> str:
    image_base64 = base64.b64encode(png_path.read_bytes()).decode("utf-8")
    response = requests.post(
        "https://api.superdocs.app/v1/documents/images/upload-base64",
        headers=HEADERS,
        json={"image_base64": image_base64},
    )
    print(f"Image upload status: {response.status_code}")
    data = response.json()
    print(data)
    return data.get("url")


# --- Step 1: extract everything ---
raw_text = extract_text(ASSET_DIR / "page_1.pdf")
seed_html = build_seed_html(raw_text)
colors = extract_palette(ASSET_DIR / "page_1.png")

print("=== Seed HTML ===")
print(seed_html)
print("\n=== Colors ===")
print(colors)

# --- Step 2: upload the flyer image so SuperDocs can embed it ---
print("\n=== Uploading image to SuperDocs ===")
image_url = upload_image_to_superdocs(ASSET_DIR / "page_1.png")
print(f"Image URL: {image_url}")

# --- Step 3: seed the session with the real copy ---
print("\n=== Seeding session with extracted copy ===")
seed_response = requests.post(
    "https://api.superdocs.app/v1/chat",
    headers=HEADERS,
    json={
        "message": "Load this content as the starting document. Do not rewrite anything yet.",
        "session_id": SESSION_ID,
        "document_html": seed_html,
    },
)
print(f"Seed status: {seed_response.status_code}")
seed_data = seed_response.json()
print(f"Chunks: {len(seed_data.get('document_changes', {}).get('updated_html', ''))} chars of HTML")

# --- Step 4: the real expansion instruction ---
color_list = ", ".join(colors)
instruction = (
    "This is the copy from a promotional flyer for a brand called 'ROOTED — Cold Brew', "
    "a clean-energy cold brew coffee product aimed at trail runners. Expand this into a full "
    "one-page leave-behind report a sales rep could hand to a retail buyer: add sections for "
    "'Product Overview', 'Why Trail Runners Choose ROOTED', 'Event Marketing Calendar', and "
    "'Contact & Ordering Information'. Keep the tone energetic and outdoorsy, matching the "
    f"original flyer. The brand's color palette is: {color_list} — mention these as the brand's "
    f"visual identity in a short 'Brand Guidelines' note at the end. Insert this image as the "
    f"header image: {image_url}"
)

print("\n=== Sending expansion instruction ===")
expand_response = requests.post(
    "https://api.superdocs.app/v1/chat",
    headers=HEADERS,
    json={"message": instruction, "session_id": SESSION_ID},
)
print(f"Expand status: {expand_response.status_code}")
expand_data = expand_response.json()
print(f"\nAI response: {expand_data.get('response')}")
print(f"\nUsage: {expand_data.get('usage')}")

# Save the result so we can inspect it
output_html = expand_data.get("document_changes", {}).get("updated_html", "")
Path("output_longform.html").write_text(output_html, encoding="utf-8")
print(f"\nSaved expanded document to output_longform.html ({len(output_html)} chars)")