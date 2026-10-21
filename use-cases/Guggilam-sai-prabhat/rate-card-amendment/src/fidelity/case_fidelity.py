"""Ties `AmendmentCase` + original contract text + export text together into
one `FidelityReport`, and writes both artifact formats.

This is the entry point the app (or a test) actually calls; everything else
in `src/fidelity/` is composable on its own for unit testing.
"""

from __future__ import annotations

from pathlib import Path

from src.amendment_case import AmendmentCase
from src.fidelity.compare import FidelityReport, compare_documents
from src.fidelity.intended_edits import derive_intended_edits
from src.fidelity.report import write_html_report, write_json_report, write_markdown_report


def build_fidelity_report(
    case: AmendmentCase,
    original_text: str,
    exported_text: str,
    export_format: str = "markdown",
) -> FidelityReport:
    """Build a `FidelityReport` for one case's original-vs-exported contract text."""

    edits = derive_intended_edits(case)
    return compare_documents(
        document_id=case.document_id,
        original_text=original_text,
        exported_text=exported_text,
        intended_edits=edits,
        original_format_hint=None,  # original is read straight from disk (markdown fixture)
        exported_format_hint=export_format,
    )


def build_excluded_contract_report(case: AmendmentCase, original_text: str, reason: str) -> FidelityReport:
    """Build a report for a contract that was never edited at all — blocked,
    requires-review, or every proposal rejected. The "export" is defined as
    identical to the original by construction (no SuperDocs session ever
    produced different text), so this always yields `byte_identical`."""

    return compare_documents(
        document_id=case.document_id,
        original_text=original_text,
        exported_text=original_text,
        intended_edits=derive_intended_edits(case),
        excluded_contract=True,
        excluded_reason=reason,
    )


def write_case_fidelity_artifacts(report: FidelityReport, output_dir: str | Path, case_id: str) -> dict[str, Path]:
    """Write the JSON + Markdown + HTML artifacts for one case's report under
    `output_dir`, named by `case_id`. Returns the written paths."""

    output_dir = Path(output_dir)
    return {
        "json": write_json_report(report, output_dir / f"{case_id}.fidelity.json"),
        "markdown": write_markdown_report(report, output_dir / f"{case_id}.fidelity.md"),
        "html": write_html_report(report, output_dir / f"{case_id}.fidelity.html"),
    }
