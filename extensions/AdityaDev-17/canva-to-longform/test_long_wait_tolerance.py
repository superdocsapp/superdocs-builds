"""
test_long_document_consistency.py — the real "page 1 to page 40"
consistency test from the card, done as a deliberate small-sample
proxy (up to 5 sections, not 40 pages) with a real, explicit
SAMPLE_MODE toggle and a hard stopping rule, per the brief's "budget
your operations" guidance.

Bug fixed here: SESSION_ID was previously a fixed hardcoded string,
so every run of this script built on top of leftover content from
every PRIOR run - producing contaminated results (topic mismatches,
phantom headings like "Core Brand Pillars" that were never requested
in the current run, "already exists" responses for sections not yet
added this run). Now generates a fresh, unique session ID every run,
so each test is genuinely isolated.

SAMPLE_MODE=true runs just 1 section first, to confirm the approach
works before spending operations on the full run - a real switch, not
just a reasoning choice about which number to pick.

Design: the brand palette is stated ONCE, on turn 1. Every subsequent
turn asks for a new section "in the same style as the rest of the
document" with NO color restatement - this tests whether SuperDocs'
own conversation memory holds visual consistency across many turns.

Measures, does not assert: every h1/h2 in the final document is
checked programmatically against the brand's primary color, and every
heading is checked for duplication - proof over assertion.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import re
import uuid
import requests

from extract_content import extract_palette
from pathlib import Path
from collections import Counter

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

DESIGN_ID = "DAHSiXKMgD4"

# Fresh, unique session every run - fixes the real contamination bug
# found when this was a hardcoded string.
SESSION_ID = f"consistency-test-{DESIGN_ID}-{uuid.uuid4().hex[:8]}"
print(f"Using fresh session: {SESSION_ID}\n")

colors = extract_palette(Path("design_assets") / DESIGN_ID / "page_1.png")
primary = colors[0]

SAMPLE_MODE = os.getenv("SAMPLE_MODE", "false").lower() == "true"

_FULL_SECTION_TOPICS = [
    "Our Sourcing Story",
    "Sustainability Commitment",
    "Retail Partner Program",
    "Athlete Ambassador Spotlights",
    "Nutritional Information",
]

SECTION_TOPICS = _FULL_SECTION_TOPICS[:1] if SAMPLE_MODE else _FULL_SECTION_TOPICS

if SAMPLE_MODE:
    print("*** SAMPLE_MODE=true — running 1 section only. Set SAMPLE_MODE=false (or unset) for the full test. ***\n")

total_ops = 0


def send_chat(message: str, document_html: str | None = None) -> dict:
    global total_ops
    payload = {"message": message, "session_id": SESSION_ID}
    if document_html is not None:
        payload["document_html"] = document_html
    response = requests.post("https://api.superdocs.app/v1/chat", headers=HEADERS, json=payload)
    data = response.json()
    ops = data.get("usage", {}).get("ops_charged", 0)
    total_ops += ops
    print(f"  status={response.status_code}  ops_charged={ops}  response={data.get('response', '')[:80]}")
    return data


def check_heading_consistency(html: str, expected_primary: str) -> list[dict]:
    heading_pattern = re.compile(r'<h[12][^>]*style="([^"]*)"[^>]*>(.*?)</h[12]>', re.DOTALL)
    results = []
    for match in heading_pattern.finditer(html):
        style, text = match.group(1), match.group(2).strip()
        color_match = re.search(r'color:\s*(#[0-9a-fA-F]{6})', style)
        color = color_match.group(1) if color_match else None
        results.append({
            "text": re.sub(r"<[^>]+>", "", text)[:50],
            "color": color,
            "on_brand": bool(color and color.lower() == expected_primary.lower()),
        })
    return results


def check_duplicate_headings(html: str) -> list[dict]:
    heading_pattern = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.DOTALL)
    texts = []
    for match in heading_pattern.finditer(html):
        clean = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        clean = re.sub(r"\s+", " ", clean)
        texts.append(clean)

    counts = Counter(t.lower() for t in texts)
    seen_originals = {}
    for t in texts:
        key = t.lower()
        seen_originals.setdefault(key, t)

    return [
        {"text": seen_originals[key], "count": count}
        for key, count in counts.items()
        if count > 1
    ]


print("Turn 1 (seed + state palette once)...")
seed_message = (
    f"Create the first section of a long-form brand document for ROOTED Cold Brew, "
    f"a clean-energy cold brew for trail runners. Use {primary} as the color for all "
    f"section headings throughout this document, consistently, for every section I add "
    f"from now on - I won't repeat this instruction again. Start with a 'Company Overview' section."
)
result = send_chat(seed_message)
current_html = result.get("document_changes", {}).get("updated_html", "")

for i, topic in enumerate(SECTION_TOPICS, start=2):
    print(f"\nTurn {i} (topic: {topic}, no color restatement)...")
    result = send_chat(f"Add a new section titled '{topic}', in the same style as the rest of the document.")
    current_html = result.get("document_changes", {}).get("updated_html", current_html)

print("\n=== Color consistency check ===")
headings = check_heading_consistency(current_html, primary)
for h in headings:
    status = "✅ on-brand" if h["on_brand"] else "❌ OFF-BRAND"
    print(f"  {status}  color={h['color']}  \"{h['text']}\"")

on_brand = sum(1 for h in headings if h["on_brand"])
total = len(headings)
print(f"\n{on_brand}/{total} headings matched the brand primary color ({primary})")

print("\n=== Duplicate section check ===")
duplicates = check_duplicate_headings(current_html)
if duplicates:
    for d in duplicates:
        print(f"  ⚠️  \"{d['text']}\" appears {d['count']} times")
else:
    print("  No duplicates found.")

print(f"\nTotal operations spent on this test: {total_ops}")

output_filename = "consistency_test_output_sample.html" if SAMPLE_MODE else "consistency_test_output.html"
Path(output_filename).write_text(current_html, encoding="utf-8")
print(f"Saved full document to {output_filename}")