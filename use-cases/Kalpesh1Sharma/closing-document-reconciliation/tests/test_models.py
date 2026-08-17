from core.models import (
    DocumentType,
    ExtractedMortgageDocument,
    FieldEvidence,
)


def test_canonical_mortgage_document_can_be_created():
    document = ExtractedMortgageDocument(
        document_type=DocumentType.LOAN_ESTIMATE,
        filename="loan_estimate.docx",

        borrower_names=FieldEvidence(
            value=["John A. Carter", "Emily Carter"],
            raw_value="John A. Carter and Emily Carter",
            supporting_quote=(
                "Applicants: John A. Carter and Emily Carter"
            ),
            source_document="loan_estimate.docx",
        ),

        property_address=FieldEvidence(
            value="812 Cedar Grove Drive, Austin, TX 78704",
            raw_value="812 Cedar Grove Drive, Austin, TX 78704",
            supporting_quote=(
                "Property Location: "
                "812 Cedar Grove Drive, Austin, TX 78704"
            ),
            source_document="loan_estimate.docx",
        ),

        loan_amount=FieldEvidence(
            value=420000.00,
            raw_value="$420,000.00",
            supporting_quote="Amount of Loan: $420,000.00",
            source_document="loan_estimate.docx",
        ),

        interest_rate=FieldEvidence(
            value=6.500,
            raw_value="6.500%",
            supporting_quote="Interest Rate: 6.500%",
            source_document="loan_estimate.docx",
        ),

        term_months=FieldEvidence(
            value=360,
            raw_value="30 years",
            supporting_quote="Loan Term: 30 years",
            source_document="loan_estimate.docx",
        ),

        escrow=FieldEvidence(
            value=True,
            raw_value="Yes",
            supporting_quote="Escrow Account: Yes",
            source_document="loan_estimate.docx",
        ),

        fees={
            "origination": FieldEvidence(
                value=4200.00,
                raw_value="$4,200.00",
                supporting_quote=(
                    "Origination Charges: $4,200.00"
                ),
                source_document="loan_estimate.docx",
            ),
            "title_services": FieldEvidence(
                value=2850.00,
                raw_value="$2,850.00",
                supporting_quote=(
                    "Title & Settlement Services: $2,850.00"
                ),
                source_document="loan_estimate.docx",
            ),
        },

        cash_to_close=FieldEvidence(
            value=91700.00,
            raw_value="$91,700.00",
            supporting_quote=(
                "Estimated Cash to Close: $91,700.00"
            ),
            source_document="loan_estimate.docx",
        ),
    )

    assert document.loan_amount.value == 420000.00
    assert document.term_months.value == 360

    assert (
        document.fees["title_services"].value
        == 2850.00
    )

    assert document.document_type == DocumentType.LOAN_ESTIMATE