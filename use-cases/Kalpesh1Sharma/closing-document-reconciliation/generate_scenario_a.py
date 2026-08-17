from pathlib import Path
import json

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


OUTPUT_DIR = Path("sample_documents/scenario_a")


def configure_document(doc: Document) -> None:
    """Apply simple consistent formatting to every synthetic document."""
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)

    styles = doc.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(10.5)


def add_header(doc: Document, title: str, subtitle: str) -> None:
    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = title_p.add_run(title)
    run.bold = True
    run.font.size = Pt(16)

    subtitle_p = doc.add_paragraph()
    subtitle_p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    run = subtitle_p.add_run(subtitle)
    run.italic = True
    run.font.size = Pt(9)

    doc.add_paragraph(
        "SYNTHETIC DEMONSTRATION DOCUMENT — "
        "No real borrower, property, lender, or transaction."
    )


def add_key_value_table(doc: Document, rows: list[tuple[str, str]]) -> None:
    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"

    header = table.rows[0].cells
    header[0].text = "Field"
    header[1].text = "Value"

    for field, value in rows:
        cells = table.add_row().cells
        cells[0].text = field
        cells[1].text = value


def create_loan_estimate() -> None:
    doc = Document()
    configure_document(doc)

    add_header(
        doc,
        "LOAN ESTIMATE",
        "Carter Residence Purchase — File SCENARIO-A-001",
    )

    doc.add_heading("Applicants and Property", level=1)

    add_key_value_table(
        doc,
        [
            ("Applicants", "John A. Carter and Emily Carter"),
            (
                "Property Location",
                "812 Cedar Grove Drive, Austin, TX 78704",
            ),
        ],
    )

    doc.add_heading("Loan Terms", level=1)

    add_key_value_table(
        doc,
        [
            ("Amount of Loan", "$420,000.00"),
            ("Interest Rate", "6.500%"),
            ("Loan Term", "30 years"),
            ("Loan Type", "Fixed Rate"),
            ("Escrow Account", "Yes"),
        ],
    )

    doc.add_heading("Estimated Closing Costs", level=1)

    add_key_value_table(
        doc,
        [
            ("Origination Charges", "$4,200.00"),
            ("Title & Settlement Services", "$2,850.00"),
            ("Estimated Cash to Close", "$91,700.00"),
        ],
    )

    doc.add_paragraph(
        "This estimate is provided solely for the synthetic "
        "SuperDocs reconciliation demonstration."
    )

    doc.save(OUTPUT_DIR / "loan_estimate.docx")


def create_closing_disclosure() -> None:
    doc = Document()
    configure_document(doc)

    add_header(
        doc,
        "CLOSING DISCLOSURE",
        "Carter Residence Purchase — File SCENARIO-A-001",
    )

    doc.add_heading("Transaction Information", level=1)

    add_key_value_table(
        doc,
        [
            ("Borrowers", "John A. Carter; Emily Carter"),
            (
                "Property",
                "812 Cedar Grove Drive, Austin, TX 78704",
            ),
        ],
    )

    doc.add_heading("Final Loan Terms", level=1)

    add_key_value_table(
        doc,
        [
            ("Loan Amount", "$420,000.00"),
            # SEEDED VARIANCE
            ("Interest Rate", "6.625%"),
            ("Loan Term", "360 months"),
            ("Escrowed Property Costs", "Yes"),
        ],
    )

    doc.add_heading("Final Loan Costs", level=1)

    add_key_value_table(
        doc,
        [
            ("Loan Costs — Origination", "$4,200.00"),
            # SEEDED SMALL VARIANCE
            ("Title Services", "$3,000.00"),
            # SEEDED VARIANCE
            ("Cash to Close", "$93,050.00"),
        ],
    )

    doc.add_paragraph(
        "All values in this document are fictional and were created "
        "for software testing."
    )

    doc.save(OUTPUT_DIR / "closing_disclosure.docx")


def create_promissory_note() -> None:
    doc = Document()
    configure_document(doc)

    add_header(
        doc,
        "FIXED RATE PROMISSORY NOTE",
        "Synthetic Note — File SCENARIO-A-001",
    )

    doc.add_paragraph(
        "FOR VALUE RECEIVED, John A. Carter and Emily Carter "
        "(collectively, the Borrowers) promise to pay the principal "
        "sum described below according to the terms of this synthetic note."
    )

    doc.add_heading("Note Terms", level=1)

    # Deliberately uses labels different from LE/CD.
    add_key_value_table(
        doc,
        [
            ("Borrowers", "John A. Carter and Emily Carter"),
            (
                "Secured Property",
                "812 Cedar Grove Drive, Austin, Texas 78704",
            ),
            ("Principal Sum", "$420,000.00"),
            ("Interest", "6.500% per annum"),
            ("Maturity", "360 monthly payments"),
            ("Escrow Requirement", "Required"),
        ],
    )

    doc.add_paragraph(
        "The first scheduled payment is due after closing. "
        "This instrument is fictional and has no legal effect."
    )

    doc.save(OUTPUT_DIR / "promissory_note.docx")


def create_settlement_statement() -> None:
    doc = Document()
    configure_document(doc)

    add_header(
        doc,
        "SETTLEMENT STATEMENT",
        "Synthetic Settlement Summary — File SCENARIO-A-001",
    )

    doc.add_heading("Settlement Parties", level=1)

    # Deliberate harmless formatting/name/address differences.
    add_key_value_table(
        doc,
        [
            ("Borrower(s)", "John Carter & Emily Carter"),
            (
                "Settlement Property",
                "812 Cedar Grove Dr., Austin, TX 78704",
            ),
        ],
    )

    doc.add_heading("Financial Summary", level=1)

    add_key_value_table(
        doc,
        [
            ("Principal Amount of New Loan", "$420,000.00"),
            ("Settlement / Title Charges", "$3,000.00"),
            ("Amount Due From Borrower", "$93,050.00"),
            ("Escrow Collected", "Yes"),
        ],
    )

    doc.add_paragraph(
        "This settlement statement is fabricated test data and "
        "does not represent a real closing."
    )

    doc.save(OUTPUT_DIR / "settlement_statement.docx")


def create_underwriting_approval() -> None:
    doc = Document()
    configure_document(doc)

    add_header(
        doc,
        "UNDERWRITING APPROVAL",
        "Final Synthetic Approval — File SCENARIO-A-001",
    )

    doc.add_heading("Approved Terms", level=1)

    add_key_value_table(
        doc,
        [
            ("Approved Borrowers", "John A. Carter / Emily Carter"),
            (
                "Approved Property",
                "812 Cedar Grove Drive, Austin, TX 78704",
            ),
            ("Approved Principal", "$420,000.00"),
            ("Approved Note Rate", "6.500%"),
            ("Amortization Term", "360 months"),
            ("Escrow Requirement", "Required"),
        ],
    )

    doc.add_heading("File-Specific Closing Reconciliation Rules", level=1)

    rules = [
        (
            "R-001",
            "The final loan amount must exactly match the "
            "approved principal amount.",
        ),
        (
            "R-002",
            "The final interest rate must exactly match the "
            "approved note rate. Any discrepancy requires a revised "
            "Closing Disclosure before funding.",
        ),
        (
            "R-003",
            "The amortization term must exactly match the approved term.",
        ),
        (
            "R-004",
            "Escrow must remain enabled unless a later written "
            "underwriting condition explicitly waives it.",
        ),
        (
            "R-005",
            "A Title & Settlement Services fee difference of up to "
            "$250.00 from the Loan Estimate is tolerable. A difference "
            "greater than $250.00 requires review and correction.",
        ),
        (
            "R-006",
            "A final cash-to-close difference greater than $500.00 "
            "from the Loan Estimate requires review and a revised "
            "disclosure request before funding.",
        ),
        (
            "R-007",
            "A borrower's middle initial may be omitted if the first "
            "and last names otherwise match.",
        ),
        (
            "R-008",
            "Standard postal street abbreviations such as Drive/Dr. "
            "and state-name abbreviations do not constitute a "
            "property-address variance when the street number, street "
            "name, city, state, and ZIP otherwise match.",
        ),
    ]

    table = doc.add_table(rows=1, cols=2)
    table.style = "Table Grid"

    table.rows[0].cells[0].text = "Rule ID"
    table.rows[0].cells[1].text = "Rule"

    for rule_id, rule_text in rules:
        row = table.add_row().cells
        row[0].text = rule_id
        row[1].text = rule_text

    doc.add_paragraph()
    doc.add_paragraph(
        "IMPORTANT: These rules are fictional file-specific rules "
        "created solely for this software demonstration. They are not "
        "statements of mortgage law, regulation, or compliance guidance."
    )

    doc.save(OUTPUT_DIR / "underwriting_approval.docx")


def create_ground_truth() -> None:
    ground_truth = {
        "scenario_id": "SCENARIO-A-001",
        "synthetic": True,
        "expected_results": {
            "loan_amount": {
                "status": "match",
                "canonical_value": 420000.00,
            },
            "interest_rate": {
                "status": "curable",
                "expected_values": {
                    "loan_estimate": 6.500,
                    "closing_disclosure": 6.625,
                    "promissory_note": 6.500,
                    "underwriting_approval": 6.500,
                },
                "rule_id": "R-002",
                "reason": (
                    "Closing Disclosure rate differs from the "
                    "approved 6.500% rate."
                ),
            },
            "term": {
                "status": "match",
                "canonical_months": 360,
            },
            "escrow": {
                "status": "match",
                "canonical_value": True,
            },
            "origination": {
                "status": "match",
                "loan_estimate": 4200.00,
                "closing_disclosure": 4200.00,
            },
            "title_services": {
                "status": "tolerable",
                "loan_estimate": 2850.00,
                "closing_disclosure": 3000.00,
                "difference": 150.00,
                "rule_id": "R-005",
            },
            "cash_to_close": {
                "status": "curable",
                "loan_estimate": 91700.00,
                "closing_disclosure": 93050.00,
                "settlement_statement": 93050.00,
                "difference": 1350.00,
                "rule_id": "R-006",
            },
            "borrower_names": {
                "status": "match_after_normalization",
                "rule_id": "R-007",
            },
            "property_address": {
                "status": "match_after_normalization",
                "rule_id": "R-008",
            },
        },
    }

    with open(
        OUTPUT_DIR / "ground_truth.json",
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(ground_truth, f, indent=2)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    create_loan_estimate()
    create_closing_disclosure()
    create_promissory_note()
    create_settlement_statement()
    create_underwriting_approval()
    create_ground_truth()

    print("Scenario A generated successfully.")
    print(f"Location: {OUTPUT_DIR.resolve()}")
    print()
    print("Created:")
    for path in sorted(OUTPUT_DIR.iterdir()):
        print(f"  - {path.name}")


if __name__ == "__main__":
    main()