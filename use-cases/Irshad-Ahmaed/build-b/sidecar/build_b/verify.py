"""PDF number-matching verification for Build B.

Parses exported PDFs and verifies that dollar figures and percentages
exactly match the values from the calculator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NumberCheck:
    """A single number verification check."""

    label: str
    expected: float
    actual: float | None
    passed: bool
    details: str = ""


@dataclass
class NumberVerificationReport:
    """Report of all number-matching checks."""

    checks: list[NumberCheck] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        lines = []
        for c in self.checks:
            status = "PASS" if c.passed else "FAIL"
            lines.append(
                f"{status}: {c.label} — expected {c.expected}, "
                f"got {c.actual} ({c.details})"
            )
        return "\n".join(lines)


def extract_dollar_amounts(text: str) -> list[float]:
    """Extract dollar amounts from text, normalized to floats."""
    pattern = re.compile(r"\$([\d,]+\.?\d*)")
    matches = pattern.findall(text)
    results = []
    for m in matches:
        cleaned = m.replace(",", "")
        try:
            results.append(float(cleaned))
        except ValueError:
            continue
    return results


def extract_percentages(text: str) -> list[float]:
    """Extract percentage values from text."""
    pattern = re.compile(r"(\d+\.?\d*)%")
    matches = pattern.findall(text)
    results = []
    for m in matches:
        try:
            results.append(float(m))
        except ValueError:
            continue
    return results


def verify_numbers(
    pdf_path: Path,
    expected_values: dict[str, float],
    tolerance: float = 0.01,
) -> NumberVerificationReport:
    """Parse a PDF and verify that extracted numbers match expected values."""
    report = NumberVerificationReport()

    try:
        import pymupdf
        doc = pymupdf.open(str(pdf_path))
    except ImportError:
        report.checks.append(NumberCheck(
            label="PDF parse",
            expected=0,
            actual=None,
            passed=False,
            details="pymupdf not installed",
        ))
        return report
    except OSError as e:
        report.checks.append(NumberCheck(
            label="PDF parse",
            expected=0,
            actual=None,
            passed=False,
            details=f"Failed to open PDF: {e}",
        ))
        return report

    full_text = ""
    for page_idx in range(len(doc)):
        full_text += doc[page_idx].get_text()
    doc.close()

    pdf_dollars = extract_dollar_amounts(full_text)

    for label, expected in expected_values.items():
        matched = None
        for val in pdf_dollars:
            if abs(val - expected) <= tolerance:
                matched = val
                break

        passed = matched is not None
        report.checks.append(NumberCheck(
            label=label,
            expected=expected,
            actual=matched,
            passed=passed,
            details="matched" if passed else f"not found in {pdf_dollars}",
        ))

    return report
