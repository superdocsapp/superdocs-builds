"""
Annual Report Production Line — MCP Server

Exposes the four pipeline tools as MCP-callable endpoints so
Claude Code / Claude Desktop can run the full workflow without
any Python scripts.

Run with:
    pip install fastmcp requests
    python mcp_server.py
"""

import json
import os
from pathlib import Path

import requests
from fastmcp import FastMCP

# ============================================================
# CONFIG
# ============================================================

API_KEY = os.environ["SUPERDOCS_API_KEY"]
BASE_URL = "https://api.superdocs.app"
SESSION_ID = "annual-report-2026"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

HERE = Path(__file__).parent
DOCUMENTS_DIR = HERE / "documents"
OUTPUT_DIR = HERE / "output"
STATE_FILE = HERE / "report_state.json"
CONSISTENCY_REPORT = HERE / "number-consistency-report.json"
RESOLUTION_REPORT = HERE / "resolution-report.json"

OUTPUT_DIR.mkdir(exist_ok=True)

# ============================================================
# MCP SERVER
# ============================================================

mcp = FastMCP(
    name="annual-report-production-line",
    description=(
        "Annual report workflow: upload sections, track review stages, "
        "audit number consistency, resolve mismatches, export PDF + HTML."
    ),
)


# ============================================================
# HELPERS
# ============================================================

def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def extract_json_from_text(text: str) -> dict | None:
    """Triple-fallback JSON parser for SuperDocs chat responses."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    else:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1:
            text = text[start:end + 1]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def superdocs_chat(message: str, approval_mode: str = "approve_all") -> dict:
    """Send a message to the SuperDocs chat endpoint."""
    response = requests.post(
        f"{BASE_URL}/v1/chat",
        headers=HEADERS,
        json={
            "message": message,
            "session_id": SESSION_ID,
            "approval_mode": approval_mode,
        },
        timeout=300,
    )
    response.raise_for_status()
    return response.json()


# ============================================================
# TOOL 1 — upload_report_sections
# ============================================================

@mcp.tool()
def upload_report_sections() -> str:
    """
    Upload all five annual report sections to SuperDocs and
    initialise review-stage tracking in report_state.json.

    Sections: Chair Statement, Strategy, Business Review,
    Governance, Financial Statements.

    Run this once at the start of a new report cycle, or when
    document content changes and you need to re-sync with SuperDocs.
    """

    DOCUMENTS = [
        ("chair-statement.html",    "Chair Statement",      "draft",          "replace"),
        ("strategy.html",           "Strategy",             "editorial_review","new_focused"),
        ("business-review.html",    "Business Review",      "finance_review", "new_focused"),
        ("governance.html",         "Governance",           "legal_review",   "new_focused"),
        ("financial-statements.html","Financial Statements","approved",       "new_focused"),
    ]

    state = {
        "report_title": "Annual Report 2026",
        "session_id": SESSION_ID,
        "documents": {},
    }

    results = []

    for filename, section, stage, open_mode in DOCUMENTS:
        path = DOCUMENTS_DIR / filename

        if not path.exists():
            return f"ERROR: {path} not found. Make sure documents/ folder is present."

        with open(path, "rb") as f:
            resp = requests.post(
                f"{BASE_URL}/v1/documents/upload",
                headers={"Authorization": f"Bearer {API_KEY}"},
                files={"file": f},
                data={"session_id": SESSION_ID, "open_mode": open_mode},
                timeout=120,
            )

        resp.raise_for_status()
        doc_id = resp.json().get("document_id", "unknown")

        state["documents"][section] = {
            "filename": filename,
            "document_id": doc_id,
            "stage": stage,
        }

        results.append(f"  ✓ {section} — {doc_id} ({stage})")

    save_json(STATE_FILE, state)

    return (
        "All five sections uploaded and state saved.\n\n"
        + "\n".join(results)
        + f"\n\nState file: {STATE_FILE}"
    )


# ============================================================
# TOOL 2 — get_review_status
# ============================================================

@mcp.tool()
def get_review_status() -> str:
    """
    Show the current review stage for every section of the
    annual report (draft / editorial_review / finance_review /
    legal_review / approved).
    """

    if not STATE_FILE.exists():
        return "No report_state.json found. Run upload_report_sections first."

    state = load_json(STATE_FILE)
    lines = [f"Report: {state.get('report_title', 'Annual Report')}\n"]

    for section, doc in state["documents"].items():
        lines.append(f"  {section}")
        lines.append(f"    Stage: {doc['stage']}")
        lines.append(f"    Doc ID: {doc['document_id']}")

    return "\n".join(lines)


# ============================================================
# TOOL 3 — set_review_stage
# ============================================================

@mcp.tool()
def set_review_stage(section: str, stage: str) -> str:
    """
    Move a report section to a new review stage.

    Args:
        section: One of: Chair Statement, Strategy, Business Review,
                 Governance, Financial Statements
        stage:   One of: draft, editorial_review, finance_review,
                 legal_review, approved
    """

    VALID_STAGES = [
        "draft", "editorial_review", "finance_review",
        "legal_review", "approved",
    ]

    if not STATE_FILE.exists():
        return "No report_state.json found. Run upload_report_sections first."

    if stage not in VALID_STAGES:
        return (
            f"Invalid stage '{stage}'.\n"
            f"Valid stages: {', '.join(VALID_STAGES)}"
        )

    state = load_json(STATE_FILE)

    if section not in state["documents"]:
        return (
            f"Unknown section '{section}'.\n"
            f"Valid sections: {', '.join(state['documents'].keys())}"
        )

    old_stage = state["documents"][section]["stage"]
    state["documents"][section]["stage"] = stage
    save_json(STATE_FILE, state)

    return (
        f"✓ {section}: {old_stage} → {stage}\n"
        f"State saved to {STATE_FILE}"
    )


# ============================================================
# TOOL 4 — run_consistency_audit
# ============================================================

@mcp.tool()
def run_consistency_audit() -> str:
    """
    Compare numeric figures across all five report sections.
    Identifies MATCHes and MISMATCHes between narrative and
    financial statements. Saves results to number-consistency-report.json.

    This is the key QA step — run it before every export.
    """

    # Local import so the tool works standalone
    import re
    from itertools import combinations

    NUMBER_PATTERN = re.compile(
        r"""
        (?P<prefix>£|\$|€|₹)?
        \s*
        (?P<value>\d+(?:,\d{3})*(?:\.\d+)?)
        \s*
        (?P<unit>million|billion|thousand|m|bn|k|%|percent)?
        """,
        re.IGNORECASE | re.VERBOSE,
    )

    def strip_html(html):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()

    def extract_numbers(html, name):
        text = strip_html(html)
        figures = []
        for m in NUMBER_PATTERN.finditer(text):
            prefix = (m.group("prefix") or "").strip()
            value = float(m.group("value").replace(",", ""))
            unit = (m.group("unit") or "").strip().lower()
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 120)
            figures.append({
                "document": name,
                "original": m.group(0).strip(),
                "prefix": prefix,
                "value": value,
                "unit": unit,
                "context": text[start:end],
            })
        return figures

    # Load documents
    doc_files = {
        "Chair Statement": "chair-statement.html",
        "Strategy": "strategy.html",
        "Business Review": "business-review.html",
        "Governance": "governance.html",
        "Financial Statements": "financial-statements.html",
    }

    documents = {}
    for name, filename in doc_files.items():
        path = DOCUMENTS_DIR / filename
        if not path.exists():
            return f"ERROR: {path} not found."
        documents[name] = path.read_text(encoding="utf-8")

    extracted = {name: extract_numbers(html, name) for name, html in documents.items()}

    pairs = []
    for left_name, right_name in combinations(extracted.keys(), 2):
        for left in extracted[left_name]:
            for right in extracted[right_name]:
                if left["prefix"] != right["prefix"]:
                    continue
                lu, ru = left["unit"], right["unit"]
                if lu and ru:
                    lp = lu in {"%", "percent", "percentage"}
                    rp = ru in {"%", "percent", "percentage"}
                    if lp != rp:
                        continue
                pairs.append({"left": left, "right": right})

    prompt = f"""
You are performing a READ-ONLY number-consistency audit of an annual report.
DO NOT edit any document.

Determine which numeric candidates refer to the SAME underlying business fact.
Identify matching figures as MATCH and conflicting figures as MISMATCH.

Return ONLY valid JSON in exactly this structure:

{{
  "findings": [
    {{
      "concept": "2025 Annual Revenue",
      "status": "MISMATCH",
      "left_document": "Business Review",
      "left_value": "£125 million",
      "right_document": "Financial Statements",
      "right_value": "£120 million",
      "explanation": "Brief explanation."
    }}
  ]
}}

Candidates:

{json.dumps(pairs, indent=2, ensure_ascii=False)}
"""

    result = superdocs_chat(prompt)
    response_text = result.get("response", "")
    report = extract_json_from_text(response_text)

    if report is None:
        return f"Could not parse consistency report.\n\nRaw response:\n{response_text}"

    save_json(CONSISTENCY_REPORT, report)

    findings = report.get("findings", [])
    mismatches = [f for f in findings if f.get("status") == "MISMATCH"]
    matches = [f for f in findings if f.get("status") == "MATCH"]

    lines = [
        f"Consistency audit complete.",
        f"  Findings: {len(findings)}",
        f"  Matches:  {len(matches)}",
        f"  Mismatches: {len(mismatches)}",
        "",
    ]

    if mismatches:
        lines.append("⚠ MISMATCHES FOUND:")
        for f in mismatches:
            lines.append(f"  {f['concept']}")
            lines.append(f"    {f['left_document']}: {f['left_value']}")
            lines.append(f"    {f['right_document']}: {f['right_value']}")
            lines.append(f"    {f['explanation']}")
        lines.append("")
        lines.append("Run resolve_mismatches next.")
    else:
        lines.append("✓ No mismatches. Safe to export.")

    return "\n".join(lines)


# ============================================================
# TOOL 5 — resolve_mismatches
# ============================================================

@mcp.tool()
def resolve_mismatches() -> str:
    """
    For each MISMATCH found by run_consistency_audit, determine
    which document is authoritative and propose the correction.
    Saves results to resolution-report.json.

    Run after run_consistency_audit when mismatches are found.
    """

    if not CONSISTENCY_REPORT.exists():
        return "No number-consistency-report.json found. Run run_consistency_audit first."

    report = load_json(CONSISTENCY_REPORT)
    mismatches = [f for f in report.get("findings", []) if f.get("status") == "MISMATCH"]

    if not mismatches:
        return "No mismatches in the consistency report. Nothing to resolve."

    state = load_json(STATE_FILE) if STATE_FILE.exists() else {}

    prompt = f"""
You are resolving cross-document inconsistencies in an annual report.

For each mismatch, determine:
1. Which document is the authoritative source
2. Which document should be corrected
3. The proposed value
4. The reason

Report workflow state (use review stage to help determine authority):
{json.dumps(state.get("documents", {}), indent=2)}

Mismatches:
{json.dumps(mismatches, indent=2)}

Return ONLY valid JSON:

{{
  "resolutions": [
    {{
      "concept": "...",
      "status": "ACTION_REQUIRED",
      "authoritative_document": "...",
      "document_to_review": "...",
      "current_value": "...",
      "proposed_value": "...",
      "reason": "..."
    }}
  ]
}}
"""

    result = superdocs_chat(prompt)
    response_text = result.get("response", "")
    resolution = extract_json_from_text(response_text)

    if resolution is None:
        return f"Could not parse resolution report.\n\nRaw:\n{response_text}"

    save_json(RESOLUTION_REPORT, resolution)

    resolutions = resolution.get("resolutions", [])
    lines = [f"Resolution report saved. {len(resolutions)} action(s) required.\n"]

    for r in resolutions:
        lines.append(f"  Concept: {r['concept']}")
        lines.append(f"  Fix:     {r['document_to_review']}")
        lines.append(f"           {r['current_value']} → {r['proposed_value']}")
        lines.append(f"  Reason:  {r['reason']}")
        lines.append("")

    lines.append("Run apply_resolution to apply the approved corrections.")
    return "\n".join(lines)


# ============================================================
# TOOL 6 — apply_resolution
# ============================================================

@mcp.tool()
def apply_resolution(concept: str) -> str:
    """
    Apply an approved resolution from resolution-report.json to
    the local document file AND to the SuperDocs session.

    Args:
        concept: The concept name to resolve, e.g. "2025 Annual Revenue".
                 Use "all" to apply every pending ACTION_REQUIRED resolution.
    """

    if not RESOLUTION_REPORT.exists():
        return "No resolution-report.json found. Run resolve_mismatches first."

    report = load_json(RESOLUTION_REPORT)
    resolutions = report.get("resolutions", [])

    if concept.lower() != "all":
        resolutions = [
            r for r in resolutions
            if r.get("concept", "").lower() == concept.lower()
        ]
        if not resolutions:
            return f"No resolution found for concept: '{concept}'"

    results = []

    for r in resolutions:
        if r.get("status") != "ACTION_REQUIRED":
            continue

        doc_name = r["document_to_review"]
        current_val = r["current_value"]
        proposed_val = r["proposed_value"]

        doc_map = {
            "Chair Statement": "chair-statement.html",
            "Strategy": "strategy.html",
            "Business Review": "business-review.html",
            "Governance": "governance.html",
            "Financial Statements": "financial-statements.html",
        }

        filename = doc_map.get(doc_name)
        if not filename:
            results.append(f"✗ Unknown document: {doc_name}")
            continue

        path = DOCUMENTS_DIR / filename

        if not path.exists():
            results.append(f"✗ File not found: {path}")
            continue

        html = path.read_text(encoding="utf-8")

        if current_val not in html:
            results.append(f"✗ '{current_val}' not found in {doc_name}")
            continue

        if html.count(current_val) > 1:
            results.append(
                f"✗ Ambiguous — '{current_val}' appears more than once in {doc_name}"
            )
            continue

        # Apply locally
        updated = html.replace(current_val, proposed_val, 1)
        path.write_text(updated, encoding="utf-8")

        # Apply via SuperDocs chat
        prompt = f"""
Apply this APPROVED correction to the annual report.

Target document: {doc_name}
Concept: {r['concept']}
Change: "{current_val}" → "{proposed_val}"
Reason: {r['reason']}

Apply the edit to {doc_name} only. Do not change any other document.
After applying, confirm with: UPDATED
"""
        try:
            sd_result = superdocs_chat(prompt)
            sd_response = sd_result.get("response", "")
            confirmed = "updated" in sd_response.lower()
            sd_status = "SuperDocs confirmed" if confirmed else "SuperDocs response unclear"
        except Exception as e:
            sd_status = f"SuperDocs error: {e}"

        results.append(
            f"✓ {doc_name}: {current_val} → {proposed_val}\n"
            f"  Local file updated. {sd_status}."
        )

    return "\n".join(results) if results else "No ACTION_REQUIRED resolutions found."


# ============================================================
# TOOL 7 — run_house_style_check
# ============================================================

@mcp.tool()
def run_house_style_check() -> str:
    """
    Check all five report sections against house style rules:
    currency format (£120 million), percentage notation (32%),
    employee count thousands separators, heading structure,
    character encoding, and document titles.

    Reports violations per document. Export is blocked if any
    violations are found.
    """

    # Inline the checks so this tool is self-contained
    import re
    from html.parser import HTMLParser

    class HeadingParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.headings = []
            self.current_tag = None
            self.current_text = []

        def handle_starttag(self, tag, attrs):
            if tag in {"h1", "h2"}:
                self.current_tag = tag
                self.current_text = []

        def handle_data(self, data):
            if self.current_tag:
                self.current_text.append(data)

        def handle_endtag(self, tag):
            if tag == self.current_tag:
                text = "".join(self.current_text).strip()
                if text:
                    self.headings.append((self.current_tag, text))
                self.current_tag = None
                self.current_text = []

    DOCUMENTS = {
        "Chair Statement": "chair-statement.html",
        "Strategy": "strategy.html",
        "Business Review": "business-review.html",
        "Governance": "governance.html",
        "Financial Statements": "financial-statements.html",
    }

    all_results = []

    for doc_name, filename in DOCUMENTS.items():
        path = DOCUMENTS_DIR / filename
        violations = []

        if not path.exists():
            all_results.append(f"✗ {doc_name}: file not found")
            continue

        html = path.read_text(encoding="utf-8")

        # Currency
        for pat in [r"\bGBP\s*\d", r"£\s*\d+(?:\.\d+)?\s*m\b", r"£\s*\d+(?:\.\d+)?\s*b\b"]:
            if re.search(pat, html, re.IGNORECASE):
                violations.append("Non-standard currency format")

        # Percentage
        if re.search(r"\b\d+(?:\.\d+)?\s+percent\b", html, re.IGNORECASE):
            violations.append("Use '%' not 'percent'")

        # Employee counts
        for m in re.finditer(r"\b\d{4,}\s+people\b", html, re.IGNORECASE):
            num = re.search(r"\d+", m.group())
            if num and "," not in num.group():
                violations.append(f"Missing thousands separator: '{m.group()}'")

        # Headings
        parser = HeadingParser()
        parser.feed(html)
        h1s = [t for tag, t in parser.headings if tag == "h1"]
        h2s = [t for tag, t in parser.headings if tag == "h2"]
        if len(h1s) != 1:
            violations.append(f"Expected 1 <h1>, found {len(h1s)}")
        elif h1s[0] != doc_name:
            violations.append(f"<h1> should be '{doc_name}', found '{h1s[0]}'")
        if not h2s:
            violations.append("No <h2> found")

        # Encoding
        for seq in ["Â£", "Â€", "â€™", "â€œ"]:
            if seq in html:
                violations.append(f"Encoding mojibake: '{seq}'")

        if violations:
            all_results.append(f"✗ {doc_name}:")
            for v in violations:
                all_results.append(f"    ✗ {v}")
        else:
            all_results.append(f"✓ {doc_name}")

    total_failures = sum(1 for r in all_results if r.startswith("✗"))

    summary = (
        "\n✓ All documents pass house style. Safe to export."
        if total_failures == 0
        else f"\n✗ {total_failures} document(s) failed. Fix before exporting."
    )

    return "\n".join(all_results) + summary


# ============================================================
# TOOL 8 — export_report
# ============================================================

@mcp.tool()
def export_report(format: str = "both") -> str:
    """
    Export the complete annual report through SuperDocs.
    Runs house style check first — blocks export on violations.

    Args:
        format: "pdf", "html", or "both" (default: "both")
    """

    # House style gate
    style_check = run_house_style_check()
    if "failed" in style_check.lower():
        return (
            "Export BLOCKED — house style violations found.\n\n"
            + style_check
            + "\n\nFix the violations above then re-run export_report."
        )

    # Load and assemble documents
    SECTION_ORDER = [
        ("Chair Statement", "chair-statement.html"),
        ("Strategy", "strategy.html"),
        ("Business Review", "business-review.html"),
        ("Governance", "governance.html"),
        ("Financial Statements", "financial-statements.html"),
    ]

    from html.parser import HTMLParser

    class BodyExtractor(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.in_body = False
            self.depth = 0
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag.lower() == "body":
                self.in_body = True
                self.depth = 1
                return
            if self.in_body:
                self.parts.append(self.get_starttag_text())
                self.depth += 1

        def handle_endtag(self, tag):
            if tag.lower() == "body" and self.in_body:
                self.depth -= 1
                if self.depth == 0:
                    self.in_body = False
                return
            if self.in_body:
                self.parts.append(f"</{tag}>")
                self.depth -= 1

        def handle_data(self, data):
            if self.in_body:
                self.parts.append(data)

        def handle_entityref(self, name):
            if self.in_body:
                self.parts.append(f"&{name};")

        def handle_charref(self, name):
            if self.in_body:
                self.parts.append(f"&#{name};")

        def get_body(self):
            return "".join(self.parts)

    sections_html = []
    for i, (title, filename) in enumerate(SECTION_ORDER, start=1):
        path = DOCUMENTS_DIR / filename
        if not path.exists():
            return f"ERROR: {path} not found."
        html = path.read_text(encoding="utf-8")
        parser = BodyExtractor()
        parser.feed(html)
        parser.close()
        body = parser.get_body()
        sections_html.append(
            f'<section class="report-section" data-section="{i}">\n{body}\n</section>'
        )

    combined = "\n".join(sections_html)

    report_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Annual Report 2026</title>
<style>
    @page {{
        size: A4;
        margin: 22mm 18mm 22mm 18mm;
        @top-center {{
            content: "Annual Report 2026";
            font-family: Arial, Helvetica, sans-serif;
            font-size: 8pt;
            color: #6b7280;
            letter-spacing: 0.05em;
        }}
        @bottom-right {{
            content: counter(page);
            font-family: Arial, Helvetica, sans-serif;
            font-size: 8pt;
            color: #6b7280;
        }}
        @bottom-left {{
            content: "Confidential";
            font-family: Arial, Helvetica, sans-serif;
            font-size: 8pt;
            color: #6b7280;
        }}
    }}
    @page :first {{
        @top-center {{ content: none; }}
        @bottom-right {{ content: none; }}
        @bottom-left {{ content: none; }}
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; padding: 0; font-family: Arial, Helvetica, sans-serif;
                  color: #1f2937; line-height: 1.55; font-size: 11pt; }}
    body {{ background: white; }}
    .report-cover {{ min-height: 240mm; display: flex; flex-direction: column;
                     justify-content: center; align-items: flex-start;
                     page-break-after: always; break-after: page; }}
    .report-cover h1 {{ font-size: 34pt; margin: 0 0 12pt 0; }}
    .report-cover p {{ font-size: 15pt; margin: 0; }}
    .toc {{ page-break-after: always; break-after: page; padding-top: 40pt; }}
    .report-section {{ page-break-before: always; break-before: page; }}
    h1 {{ font-size: 25pt; margin-top: 0; margin-bottom: 18pt; }}
    h2 {{ font-size: 17pt; margin-top: 22pt; margin-bottom: 10pt;
          page-break-after: avoid; }}
    p {{ margin: 0 0 10pt 0; }}
    strong {{ font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; margin: 14pt 0; page-break-inside: avoid; }}
    th, td {{ border: 1px solid #999; padding: 6pt; text-align: left; vertical-align: top; }}
</style>
</head>
<body>

<div class="report-cover">
    <h1>Annual Report 2026</h1>
    <p>Annual and Integrated Report</p>
</div>

<div class="toc">
    <h2 style="font-size: 18pt; margin-bottom: 24pt; border-bottom: 2px solid #222; padding-bottom: 8pt;">
        Contents
    </h2>
    <table style="border: none;">
        <tr><td style="border:none;padding:6pt 0;">Chair Statement</td><td style="border:none;text-align:right;">3</td></tr>
        <tr><td style="border:none;padding:6pt 0;">Strategy</td><td style="border:none;text-align:right;">5</td></tr>
        <tr><td style="border:none;padding:6pt 0;">Business Review</td><td style="border:none;text-align:right;">7</td></tr>
        <tr><td style="border:none;padding:6pt 0;">Governance</td><td style="border:none;text-align:right;">9</td></tr>
        <tr><td style="border:none;padding:6pt 0;">Financial Statements</td><td style="border:none;text-align:right;">11</td></tr>
    </table>
</div>

{combined}

</body>
</html>"""

    # Save source HTML
    source_file = OUTPUT_DIR / "annual-report-2026-source.html"
    source_file.write_text(report_html, encoding="utf-8")

    formats = ["pdf", "html"] if format == "both" else [format]
    results = [f"✓ House style passed. Exporting {', '.join(formats).upper()}...\n"]

    for fmt in formats:
        out_file = OUTPUT_DIR / f"annual-report-2026.{fmt}"
        resp = requests.post(
            f"{BASE_URL}/v1/documents/export",
            headers=HEADERS,
            json={
                "html": report_html,
                "format": fmt,
                "options": {
                    "filename": "annual-report-2026",
                    "source_filename": "annual-report-2026.html",
                },
            },
            timeout=300,
        )
        resp.raise_for_status()

        out_file.write_bytes(resp.content)
        size = out_file.stat().st_size
        results.append(f"  ✓ {fmt.upper()}: {out_file} ({size:,} bytes)")

    return "\n".join(results)


# ============================================================
# ENTRYPOINT
# ============================================================

if __name__ == "__main__":
    mcp.run()