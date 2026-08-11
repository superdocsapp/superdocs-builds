import pytest
from backend.app.services.accessibility import AccessibilityService, AccessibilityIssue

def test_heading_order_correction():
    service = AccessibilityService()
    
    # Heading level jump (H1 followed directly by H3)
    sample_text = (
        "# Main Heading\n"
        "Some paragraph content.\n"
        "### Nested Incorrect Heading\n"
        "More content."
    )
    
    audit = service.audit_document(sample_text)
    
    # Assert that the heading hierarchy issue is detected
    heading_issues = [iss for iss in audit.issues if iss.issue_type == "heading_hierarchy"]
    assert len(heading_issues) == 1
    assert "Line 3" in heading_issues[0].location
    assert heading_issues[0].can_auto_fix is True
    
    # Remediate and verify it becomes h2
    res = service.remediate_document(sample_text, {})
    assert "<h1>Main Heading</h1>" in res.remediated_html
    assert "<h2>Nested Incorrect Heading</h2>" in res.remediated_html
    assert "<h3>" not in res.remediated_html
    
    # Check that plain language report mentions the correction
    assert "Remediated 'Nested Incorrect Heading' from level 3 to 2" in res.plain_language_report

def test_missing_alt_text_detection_and_override():
    service = AccessibilityService()
    
    sample_text = (
        "# Compliance document\n"
        "Here is the system architecture diagram:\n"
        "![](https://example.com/art.png)\n"
        "And a regular screenshot:\n"
        "![Alt text provided](https://example.com/screen.png)"
    )
    
    audit = service.audit_document(sample_text)
    
    # Verify missing alt text is flagged
    alt_issues = [iss for iss in audit.issues if iss.issue_type == "missing_alt_text"]
    assert len(alt_issues) == 1
    assert "https://example.com/art.png" in alt_issues[0].location
    assert alt_issues[0].can_auto_fix is False  # Must be fixed by user inputs
    
    # Test user override
    overrides = {"https://example.com/art.png": "Overridden descriptive alt text for diagram"}
    res = service.remediate_document(sample_text, overrides)
    
    # Check output contains HTML img with corrected alt text
    assert '<img src="https://example.com/art.png" alt="Overridden descriptive alt text for diagram" />' in res.remediated_html
    assert '<img src="https://example.com/screen.png" alt="Alt text provided" />' in res.remediated_html
    
    # Verify report records user provided fix
    assert "Overridden descriptive alt text for diagram" in res.plain_language_report
    assert "[USER-FIX]" in res.plain_language_report

def test_list_and_table_semantics():
    service = AccessibilityService()
    
    sample_text = (
        "# Lists and Tables\n"
        "- First Bullet Item\n"
        "- Second Bullet Item\n"
        "\n"
        "1. First Numbered Item\n"
        "2. Second Numbered Item\n"
        "\n"
        "| Header A | Header B |\n"
        "|---|---|\n"
        "| Row 1 Col A | Row 1 Col B |\n"
        "| Row 2 Col A | Row 2 Col B |"
    )
    
    audit = service.audit_document(sample_text)
    
    # Verify list and table semantics issues/info are flagged
    list_issues = [iss for iss in audit.issues if iss.issue_type == "list_semantics"]
    table_issues = [iss for iss in audit.issues if iss.issue_type == "table_semantics"]
    assert len(list_issues) == 1
    assert len(table_issues) == 1
    
    # Remediate and verify structure
    res = service.remediate_document(sample_text, {})
    
    # Verify lists
    assert "<ul>" in res.remediated_html
    assert "<li>First Bullet Item</li>" in res.remediated_html
    assert "</ul>" in res.remediated_html
    assert "<ol>" in res.remediated_html
    assert "<li>First Numbered Item</li>" in res.remediated_html
    assert "</ol>" in res.remediated_html
    
    # Verify table
    assert "<table>" in res.remediated_html
    assert "<thead>" in res.remediated_html
    assert "<th>Header A</th>" in res.remediated_html
    assert "<tbody>" in res.remediated_html
    assert "<td>Row 1 Col A</td>" in res.remediated_html
    assert "</table>" in res.remediated_html

def test_reading_order_limitations_and_disclaimer():
    service = AccessibilityService()
    
    # 1. Text without multicolumn
    text_normal = "# Title\nParagraph content."
    res_normal = service.remediate_document(text_normal, {})
    assert "verification of reading order is limited" in res_normal.plain_language_report.lower()
    assert "[WARNING]" in res_normal.plain_language_report
    
    # 2. Text with potential multicolumn pipe indicators
    text_multicol = "Left Column Content  |  Right Column Content"
    res_multicol = service.remediate_document(text_multicol, {})
    assert "pipe-separated values" in res_multicol.plain_language_report.lower()
    
    # 3. PDF/UA, Tagged PDF compliance disclaimer assertions
    assert "DOES NOT claim or guarantee PDF/UA compliance" in res_normal.plain_language_report
    assert "tagged-PDF compliance" in res_normal.plain_language_report
    assert "WCAG certification" in res_normal.plain_language_report
    assert "complete accessibility" in res_normal.plain_language_report
    assert "audited accessibility certification" in res_normal.plain_language_report

def test_file_upload_endpoint(client):
    """
    Verifies that check-file endpoint works with a multi-part file upload.
    """
    file_content = (
        "# Fictional Compliance Document\n"
        "### Level 3 Heading Jump\n"
        "Some sample reading order text.\n"
        "![](https://example.com/art.png)"
    )
    
    response = client.post(
        "/api/v1/accessibility/check-file",
        files={"file": ("fictional_doc.md", file_content.encode("utf-8"), "text/markdown")}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "issues" in data
    assert len(data["issues"]) > 0
    assert any(iss["issue_type"] == "heading_hierarchy" for iss in data["issues"])
    assert any(iss["issue_type"] == "missing_alt_text" for iss in data["issues"])
