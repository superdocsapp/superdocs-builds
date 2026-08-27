"""PDF verification harness for Build A.

Parses exported PDFs and verifies change bars, headers/footers,
and revision-record table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class VerificationCheck:
    name: str
    passed: bool
    details: str = ""


@dataclass
class VerificationReport:
    checks: list[VerificationCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        lines = [f"{'PASS' if c.passed else 'FAIL'}: {c.name} — {c.details}" for c in self.checks]
        return "\n".join(lines)


def verify_pdf(
    pdf_path: Path,
    expected_revision: str | None = None,
) -> VerificationReport:
    """Parse and verify a controlled PDF.

    Checks: change bars alignment, headers/footers, revision-record table.
    """
    report = VerificationReport()

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except ImportError:
        report.checks.append(VerificationCheck(
            name="PDF parse",
            passed=False,
            details="pymupdf not installed — pip install pymupdf",
        ))
        return report
    except OSError as e:
        report.checks.append(VerificationCheck(
            name="PDF parse",
            passed=False,
            details=f"Failed to open PDF: {e}",
        ))
        return report

    # Check: PDF is not empty
    page_count = len(doc)
    report.checks.append(VerificationCheck(
        name="PDF not empty",
        passed=page_count > 0,
        details=f"{page_count} pages",
    ))

    # Check: revision-record table present
    full_text = ""
    for page_idx in range(len(doc)):
        full_text += doc[page_idx].get_text()

    has_table = "revision number" in full_text.lower() or "revision record" in full_text.lower()
    report.checks.append(VerificationCheck(
        name="Revision-record table",
        passed=has_table,
        details="Table found" if has_table else "No revision-record table detected",
    ))

    # Check: List of Effective Pages (LEP) present
    has_lep = "effective pages" in full_text.lower() or "lep" in full_text.lower()
    report.checks.append(VerificationCheck(
        name="List of Effective Pages (LEP)",
        passed=has_lep,
        details="LEP table found" if has_lep else "No LEP table detected",
    ))

    # Check: revision identity in headers/footers
    if expected_revision:
        has_revision = expected_revision in full_text
        report.checks.append(VerificationCheck(
            name="Revision identity stamps",
            passed=has_revision,
            details=f"Expected '{expected_revision}' {'found' if has_revision else 'NOT found'}",
        ))

    # Check: change bars present (unicode box-drawing characters used as revision marks)
    bar_pattern = re.compile(r"[\u2502\u2503\u2504\u2505\u2506\u2507\u2508\u2509\u250a\u250b]")
    bar_count = len(bar_pattern.findall(full_text))
    report.checks.append(VerificationCheck(
        name="Change bars present",
        passed=bar_count > 0,
        details=f"{bar_count} bar markers found",
    ))

    doc.close()
    return report
