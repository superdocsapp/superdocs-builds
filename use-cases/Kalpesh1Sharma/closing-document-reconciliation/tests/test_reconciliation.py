from core.models import (
    Classification,
    DocumentType,
    FieldObservation,
    FileRule,
    FindingStatus,
)
from core.normalize import (
    addresses_match,
    borrower_sets_match_under_middle_initial_rule,
)

from core.reconcile import (
    reconcile_numeric_field,
    reconcile_text_field,
)


def observation(
    document_type: DocumentType,
    filename: str,
    value: float | None,
    raw_value: str | None,
) -> FieldObservation:
    return FieldObservation(
        document_type=document_type,
        filename=filename,
        value=value,
        raw_value=raw_value,
        supporting_quote=(
            f"Synthetic supporting quote: {raw_value}"
            if raw_value is not None
            else None
        ),
    )


RATE_RULE = FileRule(
    rule_id="R-002",
    rule_text=(
        "The final interest rate must exactly match the approved "
        "note rate."
    ),
    source_document="underwriting_approval.docx",
    supporting_quote=(
        "The final interest rate must exactly match the approved "
        "note rate."
    ),
)

TITLE_RULE = FileRule(
    rule_id="R-005",
    rule_text=(
        "A Title & Settlement Services fee difference of up to "
        "$250.00 from the Loan Estimate is tolerable."
    ),
    source_document="underwriting_approval.docx",
    supporting_quote=(
        "A Title & Settlement Services fee difference of up to "
        "$250.00 from the Loan Estimate is tolerable."
    ),
)

CASH_RULE = FileRule(
    rule_id="R-006",
    rule_text=(
        "A final cash-to-close difference greater than $500.00 "
        "from the Loan Estimate requires review."
    ),
    source_document="underwriting_approval.docx",
    supporting_quote=(
        "A final cash-to-close difference greater than $500.00 "
        "from the Loan Estimate requires review."
    ),
)

NAME_RULE = FileRule(
    rule_id="R-007",
    rule_text=(
        "A borrower's middle initial may be omitted if the "
        "first and last names otherwise match."
    ),
    source_document="underwriting_approval.docx",
    supporting_quote=(
        "A borrower's middle initial may be omitted if the "
        "first and last names otherwise match."
    ),
)


ADDRESS_RULE = FileRule(
    rule_id="R-008",
    rule_text=(
        "Standard postal street abbreviations such as Drive/Dr. "
        "do not constitute a property-address variance."
    ),
    source_document="underwriting_approval.docx",
    supporting_quote=(
        "Standard postal street abbreviations such as Drive/Dr. "
        "do not constitute a property-address variance."
    ),
)


def test_loan_amount_matches():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            420000,
            "$420,000.00",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            420000,
            "$420,000.00",
        ),
        observation(
            DocumentType.PROMISSORY_NOTE,
            "promissory_note.docx",
            420000,
            "$420,000.00",
        ),
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            420000,
            "$420,000.00",
        ),
    ]

    result = reconcile_numeric_field(
        field_name="loan_amount",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        tolerance=0,
    )

    assert result.status == FindingStatus.MATCH
    assert result.classification == Classification.NOT_APPLICABLE


def test_interest_rate_variance_is_curable():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            6.500,
            "6.500%",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            6.625,
            "6.625%",
        ),
        observation(
            DocumentType.PROMISSORY_NOTE,
            "promissory_note.docx",
            6.500,
            "6.500%",
        ),
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            6.500,
            "6.500%",
        ),
    ]

    result = reconcile_numeric_field(
        field_name="interest_rate",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        tolerance=0,
        applicable_rule=RATE_RULE,
        curable_action=(
            "Request a revised Closing Disclosure reflecting "
            "the approved interest rate."
        ),
    )

    assert result.status == FindingStatus.VARIANCE
    assert result.classification == Classification.CURABLE
    assert result.requires_human_review is True
    assert "R-002" in result.explanation


def test_title_fee_variance_is_tolerable():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            2850,
            "$2,850.00",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            3000,
            "$3,000.00",
        ),
        observation(
            DocumentType.SETTLEMENT_STATEMENT,
            "settlement_statement.docx",
            3000,
            "$3,000.00",
        ),
    ]

    result = reconcile_numeric_field(
        field_name="title_services",
        observations=observations,
        reference_document=DocumentType.LOAN_ESTIMATE,
        tolerance=250,
        applicable_rule=TITLE_RULE,
    )

    assert result.status == FindingStatus.VARIANCE
    assert result.classification == Classification.TOLERABLE
    assert result.requires_human_review is False
    assert "150" in result.explanation
    assert "250" in result.explanation


def test_cash_to_close_variance_is_curable():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            91700,
            "$91,700.00",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            93050,
            "$93,050.00",
        ),
        observation(
            DocumentType.SETTLEMENT_STATEMENT,
            "settlement_statement.docx",
            93050,
            "$93,050.00",
        ),
    ]

    result = reconcile_numeric_field(
        field_name="cash_to_close",
        observations=observations,
        reference_document=DocumentType.LOAN_ESTIMATE,
        tolerance=500,
        applicable_rule=CASH_RULE,
        curable_action=(
            "Prepare a revised disclosure request before funding."
        ),
    )

    assert result.status == FindingStatus.VARIANCE
    assert result.classification == Classification.CURABLE
    assert result.requires_human_review is True
    assert "1350" in result.explanation
    assert "500" in result.explanation


def test_missing_reference_never_gets_inferred():
    observations = [
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            None,
            None,
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            6.625,
            "6.625%",
        ),
    ]

    result = reconcile_numeric_field(
        field_name="interest_rate",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        tolerance=0,
        applicable_rule=RATE_RULE,
    )

    assert result.status == FindingStatus.INSUFFICIENT_EVIDENCE
    assert result.classification == Classification.UNCLASSIFIED
    assert result.requires_human_review is True



def test_borrower_names_match_after_permitted_normalization():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            "John A. Carter and Emily Carter",
            "John A. Carter and Emily Carter",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            "John A. Carter; Emily Carter",
            "John A. Carter; Emily Carter",
        ),
        observation(
            DocumentType.SETTLEMENT_STATEMENT,
            "settlement_statement.docx",
            "John Carter & Emily Carter",
            "John Carter & Emily Carter",
        ),
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            "John A. Carter / Emily Carter",
            "John A. Carter / Emily Carter",
        ),
    ]

    result = reconcile_text_field(
        field_name="borrower_names",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        comparator=borrower_sets_match_under_middle_initial_rule,
        applicable_rule=NAME_RULE,
    )

    assert result.status == FindingStatus.MATCH
    assert result.requires_human_review is False
    assert "R-007" in result.explanation


def test_property_addresses_match_after_permitted_normalization():
    observations = [
        observation(
            DocumentType.LOAN_ESTIMATE,
            "loan_estimate.docx",
            "812 Cedar Grove Drive, Austin, TX 78704",
            "812 Cedar Grove Drive, Austin, TX 78704",
        ),
        observation(
            DocumentType.PROMISSORY_NOTE,
            "promissory_note.docx",
            "812 Cedar Grove Drive, Austin, Texas 78704",
            "812 Cedar Grove Drive, Austin, Texas 78704",
        ),
        observation(
            DocumentType.SETTLEMENT_STATEMENT,
            "settlement_statement.docx",
            "812 Cedar Grove Dr., Austin, TX 78704",
            "812 Cedar Grove Dr., Austin, TX 78704",
        ),
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            "812 Cedar Grove Drive, Austin, TX 78704",
            "812 Cedar Grove Drive, Austin, TX 78704",
        ),
    ]

    result = reconcile_text_field(
        field_name="property_address",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        comparator=addresses_match,
        applicable_rule=ADDRESS_RULE,
    )

    assert result.status == FindingStatus.MATCH
    assert result.requires_human_review is False
    assert "R-008" in result.explanation


def test_genuinely_different_borrower_is_not_hidden():
    observations = [
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            "John A. Carter / Emily Carter",
            "John A. Carter / Emily Carter",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            "John A. Carter; Emma Carter",
            "John A. Carter; Emma Carter",
        ),
    ]

    result = reconcile_text_field(
        field_name="borrower_names",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        comparator=borrower_sets_match_under_middle_initial_rule,
        applicable_rule=NAME_RULE,
    )

    assert result.status == FindingStatus.VARIANCE
    assert result.requires_human_review is True


def test_genuinely_different_property_is_not_hidden():
    observations = [
        observation(
            DocumentType.UNDERWRITING_APPROVAL,
            "underwriting_approval.docx",
            "812 Cedar Grove Drive, Austin, TX 78704",
            "812 Cedar Grove Drive, Austin, TX 78704",
        ),
        observation(
            DocumentType.CLOSING_DISCLOSURE,
            "closing_disclosure.docx",
            "814 Cedar Grove Drive, Austin, TX 78704",
            "814 Cedar Grove Drive, Austin, TX 78704",
        ),
    ]

    result = reconcile_text_field(
        field_name="property_address",
        observations=observations,
        reference_document=DocumentType.UNDERWRITING_APPROVAL,
        comparator=addresses_match,
        applicable_rule=ADDRESS_RULE,
    )

    assert result.status == FindingStatus.VARIANCE
    assert result.requires_human_review is True

