"""Core enums for M&A Closing-Binder Assembler."""

from enum import Enum


class ExecutionStatus(str, Enum):
    """Document execution / signature status."""
    FULLY_EXECUTED = "FULLY_EXECUTED"
    PARTIALLY_EXECUTED = "PARTIALLY_EXECUTED"
    UNSIGNED_DRAFT = "UNSIGNED_DRAFT"
    NON_SIGNATURE_DOC = "NON_SIGNATURE_DOC"
    MISSING = "MISSING"


class SignatureType(str, Enum):
    """Detected signature technology."""
    DOCUSIGN = "DOCUSIGN"
    ADOBESIGN = "ADOBESIGN"
    WET_INK = "WET_INK"
    ELECTRONIC_TYPED = "ELECTRONIC_TYPED"
    BLANK_PLACEHOLDER = "BLANK_PLACEHOLDER"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class MatchConfidence(str, Enum):
    """Confidence level of semantic document-to-checklist match."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNMATCHED = "UNMATCHED"


class DocumentCategory(str, Enum):
    """Standard M&A transaction document category."""
    PRIMARY_AGREEMENT = "I. Primary Transaction Agreements"
    ANCILLARY_AGREEMENT = "II. Ancillary & Commercial Agreements"
    CORPORATE_GOVERNANCE = "III. Corporate Governance & Resolutions"
    REGULATORY_CONSENT = "IV. Regulatory Filings & Third-Party Consents"
    OFFICER_CERTIFICATE = "V. Officer Certificates & Legal Opinions"
    FINANCIAL_CLOSING = "VI. Funds Flow & Financial Deliverables"
    DISCLOSURE_SCHEDULE = "VII. Disclosure Schedules & Exhibits"
    POST_CLOSING = "VIII. Post-Closing Covenants & Filings"


class PriorityLevel(str, Enum):
    """Priority level for closing checklist item."""
    MANDATORY_CLOSING_CONDITION = "MANDATORY_CLOSING_CONDITION"
    REQUIRED_DELIVERABLE = "REQUIRED_DELIVERABLE"
    POST_CLOSING_OBLIGATION = "POST_CLOSING_OBLIGATION"
    OPTIONAL_CONVENIENCE = "OPTIONAL_CONVENIENCE"
