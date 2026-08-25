from enum import Enum


class SupplierTier(str, Enum):
    TIER_1_STRATEGIC = "TIER_1_STRATEGIC"
    TIER_2_MANUFACTURING = "TIER_2_MANUFACTURING"
    TIER_3_COMMODITY = "TIER_3_COMMODITY"


class Region(str, Enum):
    EU = "EU"
    NORTH_AMERICA = "NORTH_AMERICA"
    APAC = "APAC"
    GLOBAL = "GLOBAL"


class AttestationStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    NORMALIZED = "NORMALIZED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    FOLLOW_UP_REQUIRED = "FOLLOW_UP_REQUIRED"
    CLOSED = "CLOSED"


class ESGPillar(str, Enum):
    ENVIRONMENTAL = "ENVIRONMENTAL"
    SOCIAL = "SOCIAL"
    GOVERNANCE = "GOVERNANCE"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    OBSERVATION = "OBSERVATION"


class ReviewDecision(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class LetterStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SENT = "SENT"
