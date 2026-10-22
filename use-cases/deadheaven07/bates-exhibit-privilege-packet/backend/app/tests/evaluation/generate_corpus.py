"""Generate synthetic evaluation corpus for Task 2.1 evidence evaluation.

Creates minimal PDFs representing the required document types:
  1. Native PDF with PII (SSN, email, phone, name, account)
  2. Multi-page PDF with PII isolated on page 2
  3. Privileged document (attorney work product)
  4. Edge-case document (invoices, dates, no PII)
  5. Misleading-filename document (filename says NOT privileged, but content is clean contract)

Run once to regenerate the corpus. The ground truth is in expected_ground_truth.json.
"""

import hashlib
import json
from pathlib import Path

import fitz

CORPUS_DIR = Path(__file__).parent / "corpus"
GROUND_TRUTH = Path(__file__).parent / "expected_ground_truth.json"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_pdf(pages_text: list[str]) -> bytes:
    doc = fitz.open()
    for text in pages_text:
        page = doc.new_page(width=612, height=792)
        y = 100
        for line in text.split("\n"):
            page.insert_text((72, y), line, fontsize=11, fontname="helv")
            y += 18
    data = doc.tobytes()
    doc.close()
    return data


def generate_corpus():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}

    # 1. Primary PII document
    text = (
        "MEDICAL BILLING STATEMENT\n"
        "\n"
        "Patient: Jane Smith\n"
        "Account: 8821-4433-2211-9900\n"
        "SSN: 123-45-6789\n"
        "Email: jane.public@example.com\n"
        "Phone: (212) 555-0199\n"
        "\n"
        "Diagnosis: cancer\n"
        "Treatment: chemotherapy cycle 3\n"
        "Total charges: $12,450.00"
    )
    data = _make_pdf([text])
    name = "primary_pii_statement.pdf"
    (CORPUS_DIR / name).write_bytes(data)
    manifest[name] = {"sha256": _sha256(data), "pages": 1}

    # 2. Multi-page PII document
    pages = [
        "FINANCIAL RECORDS - COVER PAGE\n"
        "\n"
        "Prepared for: Wilson Holdings LLC\n"
        "Period: Q1 2026\n"
        "Status: Confidential",
        "EMPLOYEE RECORD\n"
        "\n"
        "Name: Bob Wilson\n"
        "SSN: 987-65-4321\n"
        "Email: bob.wilson@example.com\n"
        "Department: Engineering\n"
        "Salary: $145,000",
        "FINANCIAL SUMMARY\n"
        "\n"
        "Revenue: $2,340,000\n"
        "Expenses: $1,890,000\n"
        "Net Income: $450,000\n"
        "\n"
        "Prepared by: Finance Department",
    ]
    data = _make_pdf(pages)
    name = "financial_records_multipage.pdf"
    (CORPUS_DIR / name).write_bytes(data)
    manifest[name] = {"sha256": _sha256(data), "pages": 3}

    # 3. Privileged document
    text = (
        "ATTORNEY WORK PRODUCT\n"
        "PRIVILEGED AND CONFIDENTIAL\n"
        "\n"
        "LITIGATION STRATEGY MEMO\n"
        "\n"
        "Re: Smith v. TechCorp, Case No. 2026-CV-1234\n"
        "\n"
        "Our strategy should focus on the breach of contract claims.\n"
        "The plaintiff has strong evidence of damages but weak causation.\n"
        "We recommend filing a motion for summary judgment on the\n"
        "intentional infliction of emotional distress claim.\n"
        "\n"
        "Prepared by: Legal Team"
    )
    data = _make_pdf([text])
    name = "internal_strategy_memo.pdf"
    (CORPUS_DIR / name).write_bytes(data)
    manifest[name] = {"sha256": _sha256(data), "pages": 1}

    # 4. Edge-case document
    text = (
        "BUSINESS CORRESPONDENCE\n"
        "\n"
        "Date: August 14, 2026\n"
        "Invoice: INV-2026-001\n"
        "Reference: FQ-0500\n"
        "\n"
        "Dear valued customer,\n"
        "Please find attached the invoice for services rendered.\n"
        "Payment is due within 30 days.\n"
        "\n"
        "Best regards,\n"
        "Accounts Department"
    )
    data = _make_pdf([text])
    name = "invoice_and_dates.pdf"
    (CORPUS_DIR / name).write_bytes(data)
    manifest[name] = {"sha256": _sha256(data), "pages": 1}

    # 5. Misleading filename document
    text = (
        "COMMERCIAL AGREEMENT\n"
        "\n"
        "This Agreement is entered into between Acme Corp and Beta Inc.\n"
        "\n"
        "1. SCOPE OF SERVICES\n"
        "   Provider shall deliver software development services.\n"
        "\n"
        "2. TERM\n"
        "   This agreement is effective for 12 months.\n"
        "\n"
        "3. COMPENSATION\n"
        "   Client shall pay $50,000 per quarter.\n"
        "\n"
        "IN WITNESS WHEREOF, the parties have executed this Agreement."
    )
    data = _make_pdf([text])
    name = "01_NOT_privileged_CONTRACT.pdf"
    (CORPUS_DIR / name).write_bytes(data)
    manifest[name] = {"sha256": _sha256(data), "pages": 1}

    # Update ground truth with actual SHA256s
    with open(GROUND_TRUTH) as f:
        gt = json.load(f)

    for doc in gt["corpus"]:
        fname = doc["filename"]
        if fname in manifest:
            doc["sha256"] = manifest[fname]["sha256"]
            doc["page_count"] = manifest[fname]["pages"]

    with open(GROUND_TRUTH, "w") as f:
        json.dump(gt, f, indent=2)

    print(f"Corpus generated: {len(manifest)} documents in {CORPUS_DIR}")
    for name, info in manifest.items():
        print(f"  {name}: {info['pages']} pages, SHA256={info['sha256'][:16]}...")


if __name__ == "__main__":
    generate_corpus()
