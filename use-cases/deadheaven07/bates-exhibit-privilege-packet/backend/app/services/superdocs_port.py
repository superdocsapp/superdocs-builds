from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass
from enum import Enum


class PIICategory(str, Enum):
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


class PrivilegeCategory(str, Enum):
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
    html: Optional[str] = None


@dataclass
class AttachmentUploadResult:
    job_id: str
    filename: str
    status: str


@dataclass
class JobStatus:
    job_id: str
    status: str
    result: Optional[dict] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


@dataclass
class ProposedChange:
    change_id: str
    operation: str
    chunk_id: Optional[str]
    old_html: Optional[str]
    new_html: Optional[str]
    ai_explanation: str
    insert_after_chunk_id: Optional[str]
    document_id: Optional[str] = None


@dataclass
class ProposedChangeBatch:
    batch_id: str
    batch_total: int
    changes: list[ProposedChange]
    awaiting_kind: str = "approval"
    continue_prompt: Optional[dict] = None


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


@dataclass
class PIIDetectionResult:
    entities: list[PIIEntity]
    total_count: int
    session_id: str
    document_id: str


@dataclass
class PrivilegeAnalysisResult:
    is_privileged: bool
    category: Optional[PrivilegeCategory]
    reason: str
    confidence: float
    key_phrases: list[str]


@dataclass
class RedactionCandidate:
    entity: PIIEntity
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None


class SuperDocsPort(ABC):
    @abstractmethod
    async def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        session_id: Optional[str] = None,
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
        document_html: Optional[str] = None,
        approval_mode: str = "approve_all",
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
        feedback: Optional[str] = None,
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
        options: Optional[dict] = None,
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
        categories: Optional[list[PIICategory]] = None,
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