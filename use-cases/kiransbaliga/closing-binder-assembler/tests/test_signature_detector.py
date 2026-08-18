"""Tests for signature detection and execution status verification."""

import pytest
from core.enums import ExecutionStatus, SignatureType
from parsers.signature_detector import SignatureDetector


@pytest.fixture
def detector():
    return SignatureDetector()


def test_docusign_executed_detection(detector):
    text = """
    AGREEMENT AND PLAN OF MERGER
    DocuSign Envelope ID: 8A7B2C3D-4E5F-6A7B-8C9D-0E1F2A3B4C5D
    IN WITNESS WHEREOF, the parties hereto have executed this Agreement.
    APEX HOLDINGS LLC
    By: /s/ Victoria Sterling
    Name: Victoria Sterling
    Title: CEO
    """
    status, blocks = detector.analyze_document_text(text, expected_parties=["APEX HOLDINGS LLC"])
    assert status == ExecutionStatus.FULLY_EXECUTED
    assert len(blocks) == 1
    assert blocks[0].is_signed is True
    assert blocks[0].signature_type in [SignatureType.DOCUSIGN, SignatureType.ELECTRONIC_TYPED]


def test_blank_placeholder_unsigned_detection(detector):
    text = """
    ESCROW AGREEMENT
    CONFIDENTIAL DRAFT - NOT FOR EXECUTION
    IN WITNESS WHEREOF, the parties have executed this Escrow Agreement.
    APEX HOLDINGS LLC
    By: _________________________
    Name: [Insert Name]
    Title: Authorized Officer

    CITIBANK, N.A.
    By: _________________________
    Name: [   ]
    Title: Vice President
    """
    status, blocks = detector.analyze_document_text(
        text, expected_parties=["APEX HOLDINGS LLC", "CITIBANK, N.A."]
    )
    assert status == ExecutionStatus.UNSIGNED_DRAFT
    assert all(b.is_signed is False for b in blocks)


def test_partially_executed_detection(detector):
    text = """
    VOTING AND SUPPORT AGREEMENT
    IN WITNESS WHEREOF, the parties have caused this Agreement to be executed.
    STOCKHOLDER:
    By: /s/ Dr. Alexander Vance
    Dr. Alexander Vance

    APEX HOLDINGS LLC:
    By: _________________________
    Name: [   ]
    Title: Managing Director
    """
    status, blocks = detector.analyze_document_text(
        text, expected_parties=["STOCKHOLDER", "APEX HOLDINGS LLC"]
    )
    assert status == ExecutionStatus.PARTIALLY_EXECUTED
    signed = [b for b in blocks if b.is_signed]
    unsigned = [b for b in blocks if not b.is_signed]
    assert len(signed) == 1
    assert len(unsigned) == 1


def test_state_certificate_non_signature_doc(detector):
    text = """
    STATE OF DELAWARE - SECRETARY OF STATE
    CERTIFICATE OF GOOD STANDING
    I, JEFFREY W. BULLOCK, SECRETARY OF STATE OF THE STATE OF DELAWARE, DO HEREBY CERTIFY...
    AUTHENTICATED UNDER THE GREAT SEAL OF THE STATE OF DELAWARE.
    """
    status, blocks = detector.analyze_document_text(text, signatures_required=False)
    assert status == ExecutionStatus.NON_SIGNATURE_DOC
    assert len(blocks) == 1
    assert blocks[0].is_signed is True
