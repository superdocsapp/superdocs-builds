import re
from typing import List, Dict, Tuple, Optional, Any
from pydantic import BaseModel

class AccessibilityIssue(BaseModel):
    id: str
    issue_type: str  # heading_hierarchy, missing_alt_text, reading_order, list_semantics, table_semantics
    location: str    # Description of where (e.g. Line 4, Image URL)
    details: str
    original_content: str
    can_auto_fix: bool

class AccessibilityAudit(BaseModel):
    original_text: str
    issues: List[AccessibilityIssue]
    detected_images: List[Dict[str, str]]  # list of url -> current_alt
    detected_headings: List[Dict[str, Any]] = [] # list of level -> text

class AccessibilityRemediationRequest(BaseModel):
    original_text: str
    alt_text_overrides: Dict[str, str]  # image_url -> new_alt

class AccessibilityRemediationResponse(BaseModel):
    remediated_html: str
    plain_language_report: str

class AccessibilityService:
    DISCLAIMER = (
        "WARNING & DISCLAIMER: This tool generates structured, semantic HTML output based on automatic heuristics "
        "and user remediation input. It DOES NOT claim or guarantee PDF/UA compliance, tagged-PDF compliance, "
        "WCAG certification, complete accessibility, or any audited accessibility certification."
    )

    def audit_document(self, text: str) -> AccessibilityAudit:
        """
        Analyzes the document for accessibility issues.
        """
        issues = []
        detected_images = []
        lines = text.split("\n")
        
        # 1. Heading Hierarchy Scan
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        headings = []  # List of tuples: (line_idx, level, text)
        for idx, line in enumerate(lines):
            match = heading_pattern.match(line.strip())
            if match:
                level = len(match.group(1))
                headings.append((idx + 1, level, match.group(2)))

        prev_level = 0
        for idx, (line_num, level, title) in enumerate(headings):
            if level > prev_level + 1:
                # Heading hierarchy jump (e.g. H1 to H3)
                issues.append(AccessibilityIssue(
                    id=f"heading_jump_{line_num}",
                    issue_type="heading_hierarchy",
                    location=f"Line {line_num}: '{title}'",
                    details=f"Heading level {level} directly follows level {prev_level} (non-sequential nesting).",
                    original_content=f"{'#' * level} {title}",
                    can_auto_fix=True
                ))
            prev_level = level

        # 2. Alt Text Scan
        # Matches markdown images: ![alt](url)
        md_img_pattern = re.compile(r"!\[(.*?)\]\((.*?)\)")
        for idx, line in enumerate(lines):
            line_num = idx + 1
            for match in md_img_pattern.finditer(line):
                alt = match.group(1).strip()
                url = match.group(2).strip()
                detected_images.append({"url": url, "current_alt": alt})
                if not alt:
                    issues.append(AccessibilityIssue(
                        id=f"alt_text_missing_{line_num}_{len(issues)}",
                        issue_type="missing_alt_text",
                        location=f"Line {line_num}, Image: {url}",
                        details="Image missing alt text (or has empty alt brackets).",
                        original_content=match.group(0),
                        can_auto_fix=False  # Requires user override alt text
                    ))

        # 3. Reading Order Checks
        # Detect if document has multi-column-like separators or disconnected single letter chunks
        has_multi_column_separator = False
        for idx, line in enumerate(lines):
            if "  |  " in line or "\t|\t" in line:
                has_multi_column_separator = True
        
        if has_multi_column_separator:
            issues.append(AccessibilityIssue(
                id="reading_order_multicol",
                issue_type="reading_order",
                location="Entire Document",
                details="Potential multi-column layout or pipe dividers detected in text. Text reading order might not flow linearly.",
                original_content="N/A",
                can_auto_fix=False
            ))

        # 4. List Semantics
        # Scan if there are plain lists that are not properly grouped or indented
        list_items_count = 0
        for line in lines:
            line_s = line.strip()
            if line_s.startswith("- ") or line_s.startswith("* ") or line_s.startswith("• ") or re.match(r"^\d+\.\s+", line_s):
                list_items_count += 1

        if list_items_count > 0:
            issues.append(AccessibilityIssue(
                id="list_semantics_info",
                issue_type="list_semantics",
                location="Multiple Lines",
                details=f"Detected {list_items_count} plain list markers. These will be converted to semantic HTML lists (<ul> or <ol>).",
                original_content="N/A",
                can_auto_fix=True
            ))

        # 5. Table Semantics
        # Scan if table row indicators are present
        table_rows_count = 0
        for line in lines:
            if line.strip().startswith("|") and line.strip().endswith("|"):
                table_rows_count += 1
        
        if table_rows_count >= 2:
            issues.append(AccessibilityIssue(
                id="table_semantics_info",
                issue_type="table_semantics",
                location="Multiple Lines",
                details=f"Detected Markdown grid table notation ({table_rows_count} lines). This will be converted to a semantic HTML <table>.",
                original_content="N/A",
                can_auto_fix=True
            ))

        return AccessibilityAudit(
            original_text=text,
            issues=issues,
            detected_images=detected_images
        )

    def remediate_document(self, text: str, alt_overrides: Dict[str, str]) -> AccessibilityRemediationResponse:
        """
        Applies fixes and returns semantic HTML and a plain-language report.
        """
        audit = self.audit_document(text)
        lines = text.split("\n")
        
        report_sections = {
            "detected": [],
            "auto_fixed": [],
            "user_fixed": [],
            "limitations": []
        }

        # First pass: heading correction tracking
        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")
        prev_level = 0
        corrected_headings = {}  # line_idx -> new_level
        
        for idx, line in enumerate(lines):
            match = heading_pattern.match(line.strip())
            if match:
                level = len(match.group(1))
                title = match.group(2)
                line_num = idx + 1
                
                if level > prev_level + 1:
                    new_level = prev_level + 1
                    corrected_headings[idx] = new_level
                    report_sections["detected"].append(f"Line {line_num}: Heading level jump ({level} -> {new_level})")
                    report_sections["auto_fixed"].append(f"Line {line_num}: Remediated '{title}' from level {level} to {new_level} (H{new_level}) to ensure sequential reading hierarchy.")
                    prev_level = new_level
                else:
                    prev_level = level

        # Process the body blocks (merging lines into paragraphs, lists, tables)
        html_blocks = []
        in_list = None  # None, "ul", "ol"
        in_table = False
        table_headers = []
        table_rows = []

        def flush_list():
            nonlocal in_list
            if in_list:
                html_blocks.append(f"</{in_list}>")
                in_list = None

        def flush_table():
            nonlocal in_table, table_headers, table_rows
            if in_table:
                tbl_html = []
                tbl_html.append("<table>")
                if table_headers:
                    tbl_html.append("<thead>")
                    tbl_html.append("<tr>")
                    for h in table_headers:
                        tbl_html.append(f"<th>{h}</th>")
                    tbl_html.append("</tr>")
                    tbl_html.append("</thead>")
                if table_rows:
                    tbl_html.append("<tbody>")
                    for row in table_rows:
                        tbl_html.append("<tr>")
                        for cell in row:
                            tbl_html.append(f"<td>{cell}</td>")
                        tbl_html.append("</tr>")
                    tbl_html.append("</tbody>")
                tbl_html.append("</table>")
                html_blocks.append("\n".join(tbl_html))
                in_table = False
                table_headers = []
                table_rows = []

        # Reading order limitations detection
        has_multi_column_separator = False

        idx = 0
        while idx < len(lines):
            line = lines[idx]
            line_s = line.strip()
            line_num = idx + 1

            if "  |  " in line_s or "\t|\t" in line_s:
                has_multi_column_separator = True

            # Case 1: Heading
            heading_match = heading_pattern.match(line_s)
            if heading_match:
                flush_list()
                flush_table()
                title = heading_match.group(2)
                level = corrected_headings.get(idx, len(heading_match.group(1)))
                
                # Inline image parsing inside heading
                title_html = self._parse_inline_images(title, alt_overrides, line_num, report_sections)
                html_blocks.append(f"<h{level}>{title_html}</h{level}>")
                idx += 1
                continue

            # Case 2: Table rows
            if line_s.startswith("|") and line_s.endswith("|"):
                flush_list()
                # Parse columns
                cells = [c.strip() for c in line_s.split("|")[1:-1]]
                
                # Check if this is a separator line (e.g. |---|---|)
                is_separator = all(re.match(r"^[-:]+$", c) for c in cells) if cells else False
                
                if is_separator:
                    # It's a table delimiter, mark header
                    if not in_table:
                        in_table = True
                    # If the previous block was treated as paragraphs, we convert the last block to headers
                    if len(table_rows) == 1 and not table_headers:
                        table_headers = table_rows.pop()
                else:
                    if not in_table:
                        in_table = True
                    table_rows.append(cells)
                idx += 1
                continue
            else:
                # Flush table if table grid ends
                if in_table:
                    flush_table()

            # Case 3: List items
            ul_match = re.match(r"^[-*•]\s+(.+)$", line_s)
            ol_match = re.match(r"^(\d+)\.\s+(.+)$", line_s)
            
            if ul_match:
                flush_table()
                if in_list != "ul":
                    flush_list()
                    in_list = "ul"
                    html_blocks.append("<ul>")
                item_content = self._parse_inline_images(ul_match.group(1), alt_overrides, line_num, report_sections)
                html_blocks.append(f"  <li>{item_content}</li>")
                report_sections["auto_fixed"].append(f"Line {line_num}: Converted plain bullet list item to semantic <li>.")
                idx += 1
                continue
            elif ol_match:
                flush_table()
                if in_list != "ol":
                    flush_list()
                    in_list = "ol"
                    html_blocks.append("<ol>")
                item_content = self._parse_inline_images(ol_match.group(2), alt_overrides, line_num, report_sections)
                html_blocks.append(f"  <li>{item_content}</li>")
                report_sections["auto_fixed"].append(f"Line {line_num}: Converted plain ordered list item to semantic <li>.")
                idx += 1
                continue
            else:
                if in_list:
                    flush_list()

            # Case 4: Blank Line
            if not line_s:
                idx += 1
                continue

            # Case 5: Standard Paragraph block
            flush_list()
            flush_table()
            para_html = self._parse_inline_images(line_s, alt_overrides, line_num, report_sections)
            html_blocks.append(f"<p>{para_html}</p>")
            idx += 1

        # Cleanup flushes
        flush_list()
        flush_table()

        # Build reading order limitations section
        if has_multi_column_separator:
            report_sections["limitations"].append(
                "Document contains pipe-separated values which were parsed as paragraphs/lines. "
                "The structural reading order cannot be automatically verified from a plain text format. "
                "Please review the exported structure to confirm proper reading flow."
            )
        else:
            report_sections["limitations"].append(
                "The text flow has been structured linearly. However, logical reading order and context flow "
                "cannot be fully verified automatically. Verification of reading order is limited by plain-text input format constraints."
            )

        # Build Report
        report_lines = []
        report_lines.append("==========================================")
        report_lines.append("   PLAIN-LANGUAGE ACCESSIBILITY REPORT    ")
        report_lines.append("==========================================")
        report_lines.append(f"\n{self.DISCLAIMER}\n")
        
        report_lines.append("## 1. ISSUES DETECTED")
        if report_sections["detected"]:
            for issue in report_sections["detected"]:
                report_lines.append(f"- [DETECTED] {issue}")
        else:
            report_lines.append("- No heading order discrepancies found.")
        
        # Check for missing/remediated image alt issues
        img_missing_count = 0
        for img in audit.detected_images:
            if not img["current_alt"]:
                img_missing_count += 1
                url = img["url"]
                report_lines.append(f"- [DETECTED] Missing Alt Text for image: '{url}'")
        if img_missing_count == 0:
            report_lines.append("- No missing alt text issues detected.")

        report_lines.append("\n## 2. AUTOMATICALLY FIXED ISSUES")
        if report_sections["auto_fixed"]:
            for fix in report_sections["auto_fixed"]:
                report_lines.append(f"- [AUTO-FIX] {fix}")
        else:
            report_lines.append("- No automatic modifications were necessary.")

        report_lines.append("\n## 3. USER-PROVIDED REMEDIATIONS")
        if report_sections["user_fixed"]:
            for fix in report_sections["user_fixed"]:
                report_lines.append(f"- [USER-FIX] {fix}")
        else:
            report_lines.append("- No user-provided alt-text corrections were applied.")

        report_lines.append("\n## 4. VERIFICATION LIMITATIONS")
        for limit in report_sections["limitations"]:
            report_lines.append(f"- [WARNING] {limit}")

        return AccessibilityRemediationResponse(
            remediated_html="\n".join(html_blocks),
            plain_language_report="\n".join(report_lines)
        )

    def _parse_inline_images(self, text: str, overrides: Dict[str, str], line_num: int, report_sections: Dict[str, List[str]]) -> str:
        """Helper to parse markdown image syntax and replace with semantic HTML img tags."""
        md_img_pattern = re.compile(r"!\[(.*?)\]\((.*?)\)")
        
        def repl(match):
            alt = match.group(1).strip()
            url = match.group(2).strip()
            
            # Check override Alt Text
            if url in overrides:
                new_alt = overrides[url].strip()
                report_sections["user_fixed"].append(f"Line {line_num}: Added user-supplied alt description: '{new_alt}' for image '{url}'.")
                return f'<img src="{url}" alt="{new_alt}" />'
            elif alt:
                return f'<img src="{url}" alt="{alt}" />'
            else:
                # Fallback empty alt
                return f'<img src="{url}" alt="" />'

        return md_img_pattern.sub(repl, text)
