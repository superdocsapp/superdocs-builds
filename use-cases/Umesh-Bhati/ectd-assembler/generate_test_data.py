import json
import os

from docx import Document
from docx.enum.text import WD_PARAGRAPH_ALIGNMENT

SECTIONS = {
    "2.5.1": {"title": "Clinical Pharmacology", "sources": ["module5/study_report_1.txt"]},
    "2.5.2": {"title": "Clinical Efficacy", "sources": ["module5/study_report_2.txt"]},
    "2.5.3": {"title": "Clinical Safety", "sources": ["module5/study_report_2.txt"]},
}

STUDY_REPORTS = {
    "study_report_1.txt": (
        "Study Report 1 - Pharmacokinetics (PK)\n"
        "Section 1.1: The drug showed a half-life of 4.5 hours in healthy volunteers.\n"
        "Section 1.2: Peak plasma concentration (Cmax) was reached at 2 hours post-dose.\n"
    ),
    "study_report_2.txt": (
        "Study Report 2 - Efficacy and Safety\n"
        "Section 2.1: In the Phase III trial, 75% of patients showed significant symptom reduction "
        "compared to 30% in placebo.\n"
        "Section 2.2: The most common adverse event was mild headache, occurring in 5% of the active group.\n"
    ),
}


def create_module2_shell(filepath: str) -> None:
    doc = Document()
    section = doc.sections[0]

    header = section.header.paragraphs[0]
    header.text = "Module 2 Clinical Summary — CONFIDENTIAL"
    header.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    footer = section.footer.paragraphs[0]
    footer.text = "eCTD Module 2 | Draft for Internal Review"
    footer.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER

    doc.add_heading("Module 2: Clinical Summary", 0)
    doc.add_paragraph(
        "This document is assembled from Module 5 study reports. "
        "Footnotes and citations should reference the source report and section."
    )

    toc_heading = doc.add_heading("Table of Contents", level=1)
    doc.add_paragraph(
        "[Table of contents will be generated after all sections are drafted.]"
    )

    for section_num, metadata in SECTIONS.items():
        doc.add_heading(f"{section_num} {metadata['title']}", level=1)
        doc.add_paragraph(f"[Drafting placeholder for {section_num}]")

    doc.save(filepath)
    print(f"Created {filepath}")


def create_module5_reports(base_dir: str) -> None:
    os.makedirs(base_dir, exist_ok=True)
    for filename, content in STUDY_REPORTS.items():
        filepath = os.path.join(base_dir, filename)
        with open(filepath, "w") as f:
            f.write(content)
        print(f"Created {filepath}")


def create_manifest(filepath: str) -> None:
    manifest_data = {"sections": SECTIONS}
    with open(filepath, "w") as f:
        json.dump(manifest_data, f, indent=2)
    print(f"Created {filepath}")


if __name__ == "__main__":
    create_module2_shell("module2_shell.docx")
    create_module5_reports("module5")
    create_manifest("manifest.json")
    print("Test data generation complete.")
