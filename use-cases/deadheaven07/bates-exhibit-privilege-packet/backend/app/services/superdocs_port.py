from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class SuperDocsUnavailableError(Exception):
    """Raised when the SuperDocs platform is unreachable (network failure,
    timeout, or 5xx), so callers can degrade to the local fallback engine."""


class PIICategory(StrEnum):
    SSN = "ssn"
    EMAIL = "email"
    PHONE = "phone"
    ACCOUNT_NUMBER = "account_number"
    MEDICAL_TERM = "medical_term"
    NAME = "name"
    ADDRESS = "address"
    DATE_OF_BIRTH = "date_of_birth"
    CREDIT_CARD = "credit_card"
    DRIVERS_LICENSE = "drivers_license"
    PASSPORT = "passport"
    OTHER = "other"


class PrivilegeCategory(StrEnum):
    ATTORNEY_CLIENT = "attorney_client"
    WORK_PRODUCT = "work_product"
    JOINT_DEFENSE = "joint_defense"
    COMMON_INTEREST = "common_interest"
    OTHER = "other"


@dataclass
class DocumentUploadResult:
    session_id: str
    document_id: str
    chunks_count: int
    version_id: str
    page_setup: dict
    html: str | None = None


@dataclass
class AttachmentUploadResult:
    job_id: str
    filename: str
    status: str


@dataclass
class JobStatus:
    job_id: str
    status: str
    result: dict | None = None
    error: str | None = None
    metadata: dict | None = None


@dataclass
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: str | None
    old_html: str | None
    new_html: str | None
    ai_explanation: str
    insert_after_chunk_id: str | None
    document_id: str | None = None


@dataclass
class ProposedChangeBatch:
    batch_id: str
    batch_total: int
    changes: list[ProposedChange]
    awaiting_kind: str = "approval"
    continue_prompt: dict | None = None


@dataclass
class ChatResult:
    response: str
    session_id: str
    updated_html: str
    version_id: str
    changes_summary: str
    usage: dict


@dataclass
class ExportResult:
    download_url: str
    filename: str
    format: str


@dataclass
class PIIEntity:
    category: PIICategory
    text: str
    page_number: int
    start_offset: int
    end_offset: int
    confidence: float
    context_before: str = ""
    context_after: str = ""
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    superdocs_change_id: str | None = None
    change_id: str = ""


@dataclass
class PIIDetectionResult:
    entities: list[PIIEntity]
    total_count: int
    session_id: str
    document_id: str
    batch_id: str = ""
    job_id: str = ""


@dataclass
class PrivilegeAnalysisResult:
    is_privileged: bool
    category: PrivilegeCategory | None
    reason: str
    confidence: float
    key_phrases: list[str]


@dataclass
class PrivilegeSuggestion:
    """AI privilege proposal surfaced as a native SuperDocs pending_change.

    A human reviewer must approve (PRIVILEGED) or reject (NOT_PRIVILEGED)
    before the decision is recorded in the privilege log.
    """

    is_privileged: bool
    category: PrivilegeCategory | None
    reason: str
    confidence: float
    key_phrases: list[str]
    change_id: str = ""
    batch_id: str = ""
    job_id: str = ""
    source: str = "superdocs"


@dataclass
class RedactionCandidate:
    entity: PIIEntity
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None


class SuperDocsPort(ABC):
    @abstractmethod
    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: str | None = None,
        return_html: bool = True,
    ) -> DocumentUploadResult:
        pass

    @abstractmethod
    async def upload_attachment(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: str,
    ) -> AttachmentUploadResult:
        pass

    @abstractmethod
    async def poll_job(self, job_id: str) -> JobStatus:
        pass

    @abstractmethod
    async def chat_async(
        self,
        message: str,
        session_id: str,
        document_html: str | None = None,
        approval_mode: str = "ask_every_time",
        model_tier: str = "core",
    ) -> str:
        pass

    @abstractmethod
    async def approve_changes(
        self,
        session_id: str,
        job_id: str,
        approved: bool,
        changes: list[dict],
        feedback: str | None = None,
    ) -> JobStatus:
        pass

    @abstractmethod
    async def continue_job(
        self,
        session_id: str,
        job_id: str,
        continue_job: bool,
    ) -> JobStatus:
        pass

    @abstractmethod
    async def export_document(
        self,
        session_id: str,
        format: str = "pdf",
        options: dict | None = None,
    ) -> ExportResult:
        pass

    @abstractmethod
    async def get_session_history(self, session_id: str) -> dict:
        pass

    @abstractmethod
    def parse_proposed_change_batch(self, content: str) -> ProposedChangeBatch:
        pass

    @abstractmethod
    async def detect_pii(
        self,
        session_id: str,
        document_id: str,
        categories: list[PIICategory] | None = None,
    ) -> PIIDetectionResult:
        pass

    @abstractmethod
    async def analyze_privilege(
        self,
        session_id: str,
        document_id: str,
    ) -> PrivilegeAnalysisResult:
        pass

    @abstractmethod
    async def apply_redactions(
        self,
        session_id: str,
        document_id: str,
        candidates: list[RedactionCandidate],
    ) -> JobStatus:
        pass

    @abstractmethod
    async def get_redaction_preview(
        self,
        session_id: str,
        document_id: str,
        candidates: list[RedactionCandidate],
    ) -> ExportResult:
        pass
