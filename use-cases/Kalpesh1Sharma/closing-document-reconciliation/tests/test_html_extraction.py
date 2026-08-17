from pathlib import Path

from core.html_extraction import (
    extract_from_superdocs_html,
    html_to_lines,
    infer_document_type,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_underwriting_title_wins_over_rule_reference_to_loan_estimate():
    lines = [
        "UNDERWRITING APPROVAL",
        "Approved Principal",
        "$420,000.00",
        "R-005 A fee difference from the Loan Estimate is tolerable.",
    ]

    assert (
        infer_document_type(
            filename="underwriting_approval.docx",
            lines=lines,
        )
        == "underwriting_approval"
    )


def test_table_cells_are_split_into_logical_lines():
    html = """
    <table>
      <tr>
        <td><p>Applicants</p></td>
        <td><p>John A. Carter and Emily Carter</p></td>
        <td><p>Property Location</p></td>
        <td><p>812 Cedar Grove Drive, Austin, TX 78704</p></td>
      </tr>
    </table>
    """

    assert html_to_lines(html) == [
        "Applicants",
        "John A. Carter and Emily Carter",
        "Property Location",
        "812 Cedar Grove Drive, Austin, TX 78704",
    ]


def test_loan_terms_heading_is_not_misread_as_loan_term_value():
    html = """
    <p>LOAN ESTIMATE</p>
    <h1>Loan Terms</h1>
    <table>
      <tr><td><p>Loan Term</p></td><td><p>30 years</p></td></tr>
    </table>
    """

    result = extract_from_superdocs_html(
        filename="loan_estimate.docx",
        document_html=html,
    )

    assert result["term"]["raw_value"] == "30 years"
    assert result["term"]["supporting_quote"] == "Loan Term 30 years"


def test_applicants_and_property_heading_does_not_become_borrower_value():
    html = """
    <p>LOAN ESTIMATE</p>
    <h1>Applicants and Property</h1>
    <table>
      <tr>
        <td><p>Applicants</p></td>
        <td><p>John A. Carter and Emily Carter</p></td>
      </tr>
    </table>
    """

    result = extract_from_superdocs_html(
        filename="loan_estimate.docx",
        document_html=html,
    )

    assert (
        result["borrower_names"]["raw_value"]
        == "John A. Carter and Emily Carter"
    )


def test_real_superdocs_closing_disclosure_property_and_escrow_labels():
    html = (
        FIXTURES
        .joinpath("closing_disclosure_superdocs.html")
        .read_text(encoding="utf-8")
    )

    result = extract_from_superdocs_html(
        filename="closing_disclosure.docx",
        document_html=html,
    )

    assert result["document_type"] == "closing_disclosure"

    assert (
        result["property_address"]["raw_value"]
        == "812 Cedar Grove Drive, Austin, TX 78704"
    )

    assert (
        result["property_address"]["supporting_quote"]
        == "Property 812 Cedar Grove Drive, Austin, TX 78704"
    )

    assert result["escrow"]["raw_value"] == "Yes"
    assert (
        result["escrow"]["supporting_quote"]
        == "Escrowed Property Costs Yes"
    )


def test_real_superdocs_closing_disclosure_seeded_values_remain_intact():
    html = (
        FIXTURES
        .joinpath("closing_disclosure_superdocs.html")
        .read_text(encoding="utf-8")
    )

    result = extract_from_superdocs_html(
        filename="closing_disclosure.docx",
        document_html=html,
    )

    assert result["loan_amount"]["raw_value"] == "$420,000.00"
    assert result["interest_rate"]["raw_value"] == "6.625%"
    assert result["term"]["raw_value"] == "360 months"
    assert result["fees"]["origination"]["raw_value"] == "$4,200.00"
    assert result["fees"]["title_services"]["raw_value"] == "$3,000.00"
    assert result["cash_to_close"]["raw_value"] == "$93,050.00"
