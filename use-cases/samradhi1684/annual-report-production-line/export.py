import os
from pathlib import Path
from html.parser import HTMLParser
from house_style import run_house_style_check
import requests


# ============================================================
# CONFIGURATION
# ============================================================

API_KEY = os.environ["SUPERDOCS_API_KEY"]

BASE_URL = "https://api.superdocs.app"

# Session containing the five annual-report documents.
SESSION_ID = "annual-report-multidoc-test"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

DOCUMENTS_DIR = Path("documents")
OUTPUT_DIR = Path("output")

OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# REPORT ORDER
# ============================================================

# This is the order in which the sections appear in the
# finished annual report.
DOCUMENTS = [
    ("Chair Statement", "chair-statement.html"),
    ("Strategy", "strategy.html"),
    ("Business Review", "business-review.html"),
    ("Governance", "governance.html"),
    ("Financial Statements", "financial-statements.html"),
]


# ============================================================
# HTML BODY EXTRACTION
# ============================================================

class BodyExtractor(HTMLParser):
    """
    Extract the contents inside <body>...</body> while
    preserving the original HTML markup.
    """

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
            self.parts.append(
                self.get_starttag_text()
            )
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.in_body:
            self.parts.append(
                self.get_starttag_text()
            )

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

    def handle_comment(self, data):
        if self.in_body:
            self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        if self.in_body:
            self.parts.append(f"<!{decl}>")

    def get_body(self):
        return "".join(self.parts)


def extract_body(html):
    """
    Extract <body> contents from a local HTML document.
    """

    parser = BodyExtractor()
    parser.feed(html)
    parser.close()

    body = parser.get_body()

    if not body.strip():
        raise ValueError(
            "Could not extract a non-empty <body> "
            "from the document."
        )

    return body





# ============================================================
# LOAD DOCUMENTS
# ============================================================

def load_document_sections():
    """
    Read all five annual-report HTML documents and return
    their body content in the defined report order.
    """

    sections = []

    print("\nLoading report sections...")

    for title, filename in DOCUMENTS:

        path = DOCUMENTS_DIR / filename

        if not path.exists():
            raise FileNotFoundError(
                f"Report document not found:\n  {path}"
            )

        html = path.read_text(
            encoding="utf-8"
        )

        body = extract_body(html)

        sections.append(
            {
                "title": title,
                "filename": filename,
                "body": body,
            }
        )

        print(
            f"  ✓ {title:<25} "
            f"{len(html):,} bytes"
        )

    return sections


# ============================================================
# BUILD COMPLETE REPORT HTML
# ============================================================

def build_report_html(sections):
    """
    Build one complete Annual Report HTML document from
    the five section documents.

    This HTML is then passed directly to the documented
    SuperDocs export endpoint.

    SuperDocs performs the final PDF/HTML rendering.
    """

    section_html = []

    for index, section in enumerate(
        sections,
        start=1,
    ):

        section_html.append(
            f"""
<section class="report-section"
         data-section="{index}">

    {section["body"]}

</section>
"""
        )

    combined_sections = "\n".join(section_html)

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

    * {{
        box-sizing: border-box;
    }}

    html,
    body {{
        margin: 0;
        padding: 0;
        font-family:
            Arial,
            Helvetica,
            sans-serif;
        color: #1f2937;
        line-height: 1.55;
        font-size: 11pt;
    }}

    body {{
        background: white;
    }}

    .report-cover {{
        min-height: 240mm;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: flex-start;
        page-break-after: always;
        break-after: page;
    }}

    .report-cover h1 {{
        font-size: 34pt;
        margin: 0 0 12pt 0;
    }}

    .report-cover p {{
        font-size: 15pt;
        margin: 0;
    }}

    .report-section {{
        page-break-before: always;
        break-before: page;
    }}

    .report-section:first-of-type {{
        page-break-before: auto;
        break-before: auto;
    }}

    h1 {{
        font-size: 25pt;
        margin-top: 0;
        margin-bottom: 18pt;
    }}

    h2 {{
        font-size: 17pt;
        margin-top: 22pt;
        margin-bottom: 10pt;
        page-break-after: avoid;
        break-after: avoid;
    }}

    h3 {{
        font-size: 13pt;
        page-break-after: avoid;
        break-after: avoid;
    }}

    p {{
        margin: 0 0 10pt 0;
    }}

    strong {{
        font-weight: 700;
    }}

    table {{
        width: 100%;
        border-collapse: collapse;
        margin: 14pt 0;
        page-break-inside: avoid;
    }}

    th,
    td {{
        border: 1px solid #999;
        padding: 6pt;
        text-align: left;
        vertical-align: top;
    }}

    thead {{
        display: table-header-group;
    }}

    tr {{
        page-break-inside: avoid;
    }}

    img {{
        max-width: 100%;
        height: auto;
    }}

    .section-divider {{
        margin: 0 0 18pt 0;
        border-bottom: 2px solid #222;
    }}

    @media print {{
        .report-section {{
            page-break-before: always;
        }}

        .report-cover {{
            page-break-after: always;
        }}
    }}

</style>

</head>

<body>

<div class="report-cover">
    <h1>Annual Report 2026</h1>
    <p>Annual and Integrated Report</p>
</div>

<div class="toc" style="page-break-after: always; break-after: page; padding-top: 40pt;">
    <h2 style="font-size: 18pt; margin-bottom: 24pt; border-bottom: 2px solid #222; padding-bottom: 8pt;">
        Contents
    </h2>
    <table style="width: 100%; border: none;">
        <tr><td style="border: none; padding: 6pt 0;">Chair Statement</td><td style="border: none; text-align: right;">3</td></tr>
        <tr><td style="border: none; padding: 6pt 0;">Strategy</td><td style="border: none; text-align: right;">5</td></tr>
        <tr><td style="border: none; padding: 6pt 0;">Business Review</td><td style="border: none; text-align: right;">7</td></tr>
        <tr><td style="border: none; padding: 6pt 0;">Governance</td><td style="border: none; text-align: right;">9</td></tr>
        <tr><td style="border: none; padding: 6pt 0;">Financial Statements</td><td style="border: none; text-align: right;">11</td></tr>
    </table>
</div>

{combined_sections}

</body>
</html>
"""

    return report_html


# ============================================================
# SUPERDOCS EXPORT
# ============================================================

def export_document(
    fmt,
    output_file,
    report_html,
):
    """
    Export the complete five-document annual report through
    the SuperDocs export endpoint.

    Instead of exporting session_id (which exports only the
    session's current document), we pass the complete report
    HTML through the documented `html` field.

    SuperDocs performs the final rendering.
    """

    payload = {
        "html": report_html,
        "format": fmt,
        "options": {
            "filename": "annual-report-2026",
            "source_filename": "annual-report-2026.html",
        },
    }

    print("\n" + "-" * 70)
    print(f"EXPORTING {fmt.upper()} THROUGH SUPERDOCS")
    print("-" * 70)

    print(f"Format: {fmt}")
    print(
        f"Input HTML: "
        f"{len(report_html):,} characters"
    )

    response = requests.post(
        f"{BASE_URL}/v1/documents/export",
        headers=HEADERS,
        json=payload,
        timeout=300,
    )

    print("Status:", response.status_code)

    if not response.ok:

        print("\nSuperDocs export failed:")

        print(response.text)

        response.raise_for_status()

    if not response.content:

        raise RuntimeError(
            f"SuperDocs returned an empty "
            f"{fmt.upper()} file."
        )

    output_file.write_bytes(
        response.content
    )

    if not output_file.exists():

        raise RuntimeError(
            f"Export file was not created:\n"
            f"  {output_file}"
        )

    size = output_file.stat().st_size

    if size == 0:

        raise RuntimeError(
            f"Export file is empty:\n"
            f"  {output_file}"
        )

    print(
        f"Saved: {output_file}"
    )

    print(
        f"Size:  {size:,} bytes"
    )

    return output_file


# ============================================================
# VERIFY HTML EXPORT
# ============================================================

def verify_html_export(path):
    """
    Verify that the exported HTML contains all five report
    sections.
    """

    html = path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    missing = []

    for title, _ in DOCUMENTS:

        if title not in html:

            missing.append(title)

    if missing:

        print("\n⚠ HTML export verification warning.")

        print(
            "Missing section headings:"
        )

        for title in missing:
            print(f"  - {title}")

        return False

    print(
        "\n✓ HTML export contains all five "
        "report sections."
    )

    for title, _ in DOCUMENTS:
        print(f"  ✓ {title}")

    return True


# ============================================================
# MAIN
# ============================================================


def main():

    print("\n" + "=" * 70)
    print("ANNUAL REPORT EXPORT")
    print("=" * 70)

    # --------------------------------------------------------
    # 0. House style gate — block export on violations
    # --------------------------------------------------------

    print("\nRunning house style check...")

    style_results = run_house_style_check()

    failures = [r for r in style_results if r["status"] == "FAIL"]

    if failures:
        print("\n✗ House style violations found. Export blocked.\n")
        for result in failures:
            print(f"  {result['document']}:")
            for v in result["violations"]:
                print(f"    ✗ {v}")
        print(
            "\nFix the violations above, then re-run export.py.\n"
            "Run house_style.py for the full report."
        )
        return

    print("✓ House style check passed. Proceeding with export.")

    try:

        # ----------------------------------------------------
        # 1. Load five report documents
        # ----------------------------------------------------

        sections = (
            load_document_sections()
        )

        # ----------------------------------------------------
        # 2. Build ONE complete report HTML
        # ----------------------------------------------------

        print(
            "\nBuilding combined Annual Report HTML..."
        )

        report_html = build_report_html(
            sections
        )

        print(
            f"✓ Combined report generated "
            f"({len(report_html):,} characters)"
        )

        # ----------------------------------------------------
        # 3. Save intermediate combined HTML
        # ----------------------------------------------------

        combined_file = (
            OUTPUT_DIR /
            "annual-report-2026-source.html"
        )

        combined_file.write_text(
            report_html,
            encoding="utf-8",
        )

        print(
            f"✓ Source HTML saved: "
            f"{combined_file}"
        )

        # ----------------------------------------------------
        # 4. Export PDF THROUGH SUPERDOCS
        # ----------------------------------------------------

        pdf_file = (
            OUTPUT_DIR /
            "annual-report-2026.pdf"
        )

        export_document(
            "pdf",
            pdf_file,
            report_html,
        )

        # ----------------------------------------------------
        # 5. Export HTML THROUGH SUPERDOCS
        # ----------------------------------------------------

        html_file = (
            OUTPUT_DIR /
            "annual-report-2026.html"
        )

        export_document(
            "html",
            html_file,
            report_html,
        )

        # ----------------------------------------------------
        # 6. Verify HTML contains all sections
        # ----------------------------------------------------

        verify_html_export(
            html_file
        )

    except requests.RequestException as exc:

        print(
            "\n✗ SuperDocs export request failed."
        )

        print(exc)

        return

    except Exception as exc:

        print(
            "\n✗ Export failed."
        )

        print(exc)

        return

    # ========================================================
    # SUMMARY
    # ========================================================

    print("\n" + "=" * 70)
    print("EXPORT COMPLETE")
    print("=" * 70)

    print("\nGenerated files:")

    print(
        f"  PDF:          "
        f"{OUTPUT_DIR / 'annual-report-2026.pdf'}"
    )

    print(
        f"  HTML:         "
        f"{OUTPUT_DIR / 'annual-report-2026.html'}"
    )

    print(
        f"  Source HTML:  "
        f"{OUTPUT_DIR / 'annual-report-2026-source.html'}"
    )

    print(
        "\n✓ Five report sections were combined "
        "into one report."
    )

    print(
        "✓ Final PDF was rendered by SuperDocs."
    )

    print(
        "✓ Final HTML was exported by SuperDocs."
    )

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()