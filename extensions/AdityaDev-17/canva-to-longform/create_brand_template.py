"""
create_brand_template.py — builds a real reference document
demonstrating ROOTED's visual system (headings, body text, table,
callout, all in the extracted brand palette) and uploads it to
SuperDocs as a reusable template. This is the templates surface from
the card - the mechanism meant to keep visual consistency from page 1
to page 40, tested properly here rather than assumed.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import base64
import requests

from extract_content import extract_palette
from pathlib import Path

API_KEY = os.environ["SUPERDOCS_API_KEY"]
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

DESIGN_ID = "DAHSiXKMgD4"
colors = extract_palette(Path("design_assets") / DESIGN_ID / "page_1.png")
primary, secondary, tertiary = colors[0], colors[1], colors[2]

template_html = f"""
<h1 style="color:{primary}; font-family:sans-serif;">ROOTED — Cold Brew Brand Template</h1>
<p style="color:{tertiary}; font-style:italic;">Fuel for the Path Less Traveled</p>

<h2 style="color:{primary}; border-bottom:2px solid {secondary}; padding-bottom:5px; font-family:sans-serif;">Section Heading Example</h2>
<p style="font-family:sans-serif; color:{tertiary};">Body text uses this earthy, outdoor-brand tone: direct, energetic,
grounded in nature. Every section heading uses the primary brand color ({primary})
with a secondary-color underline ({secondary}).</p>

<h2 style="color:{primary}; border-bottom:2px solid {secondary}; padding-bottom:5px; font-family:sans-serif;">Example Data Table</h2>
<table style="border-collapse:collapse; width:100%;">
  <tr style="background-color:{primary}; color:white;">
    <th style="padding:8px; text-align:left;">Column A</th>
    <th style="padding:8px; text-align:left;">Column B</th>
  </tr>
  <tr>
    <td style="padding:8px; border-bottom:1px solid {secondary};">Example row 1</td>
    <td style="padding:8px; border-bottom:1px solid {secondary};">Data</td>
  </tr>
</table>

<blockquote style="border-left:4px solid {primary}; padding-left:15px; color:{tertiary}; font-style:italic;">
Callout/quote blocks use a left border in the primary brand color.
</blockquote>

<p style="font-size:0.85em; color:{secondary};">Brand palette reference: {', '.join(colors)}</p>
"""

# Save locally so we can also inspect it directly
Path("brand_template.html").write_text(template_html, encoding="utf-8")

encoded = base64.b64encode(template_html.encode("utf-8")).decode("utf-8")

response = requests.post(
    "https://api.superdocs.app/v1/templates/upload-base64",
    headers=HEADERS,
    json={
        "file_base64": encoded,
        "filename": "rooted-brand-template.html",
    },
)

print(f"Template upload status: {response.status_code}")
print(response.json())