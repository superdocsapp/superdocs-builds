"""Core data models for M&A Closing-Binder Assembler."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .enums import DocumentCategory, ExecutionStatus, MatchConfidence, PriorityLevel, SignatureType


class SignatureBlock(BaseModel):
    """Represents a detected signature block in a document."""
    party_name: str = Field(description="Name of the party or signatory")
    party_entity: Optional[str] = Field(default=None, description="Legal entity represented (e.g. Acme Corp LLC)")
    title: Optional[str] = Field(default=None, description="Corporate title (e.g. Chief Executive Officer)")
    is_signed: bool = Field(default=False, description="Whether an executed signature or digital seal was detected")
    signature_type: SignatureType = Field(default=SignatureType.BLANK_PLACEHOLDER)
    page_number: int = Field(default=1, description="Page number where signature block was found")
    raw_snippet: Optional[str] = Field(default=None, description="Raw text snippet of signature block")
    evidence: Optional[str] = Field(default=None, description="Explanation/evidence for signature detection")


class DocumentMetadata(BaseModel):
    """Metadata and extracted content of an ingested file."""
    doc_id: str = Field(description="Unique document identifier")
    original_filename: str = Field(description="Uploaded filename (often messy)")
    file_type: str = Field(description="Extension: pdf, docx, txt, md")
    file_path: str = Field(description="Local file path on disk")
    page_count: int = Field(default=1, description="Total number of pages")
    raw_text: str = Field(default="", description="Extracted full plain text")
    detected_title: Optional[str] = Field(default=None, description="Extracted legal title from document header/recitals")
    detected_parties: List[str] = Field(default_factory=list, description="Extracted legal entities / contracting parties")
    detected_date: Optional[str] = Field(default=None, description="Extracted execution / effective date")
    governing_law: Optional[str] = Field(default=None, description="Detected governing jurisdiction (e.g. Delaware, New York)")
    signature_blocks: List[SignatureBlock] = Field(default_factory=list, description="All detected signature blocks")
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.UNSIGNED_DRAFT)
    is_scanned_ocr: bool = Field(default=False, description="Whether document was parsed via OCR/image extract")


class ChecklistItem(BaseModel):
    """An individual line item on the M&A closing checklist."""
    item_id: str = Field(description="Unique item identifier (e.g. ITEM-01, ITEM-02)")
    tab_number: int = Field(description="1-indexed tab number in the closing binder structure")
    tab_label: str = Field(description="Formatted tab label (e.g. 'Tab 01', 'Tab 14(a)')")
    category: DocumentCategory = Field(default=DocumentCategory.PRIMARY_AGREEMENT)
    title: str = Field(description="Official title of the transaction document")
    description: Optional[str] = Field(default=None, description="Scope or description of document")
    required_parties: List[str] = Field(default_factory=list, description="Expected signatories / entities")
    signatures_required: bool = Field(default=True, description="False for unilateral state filings / certificates")
    priority: PriorityLevel = Field(default=PriorityLevel.MANDATORY_CLOSING_CONDITION)
    governing_law: Optional[str] = Field(default=None, description="Expected governing law")
    responsible_counsel: Optional[str] = Field(default="Buyer's Counsel", description="Party responsible for delivering item")
    notes: Optional[str] = Field(default=None, description="Special closing instructions or cross-references")


class ClosingChecklist(BaseModel):
    """Complete M&A Closing Checklist specification."""
    deal_name: str = Field(description="Deal codename or title (e.g. 'Project Titan - Acquisition of CloudScale Inc.')")
    buyer_entity: str = Field(description="Name of buyer / acquirer (e.g. 'Apex Holdings LLC')")
    target_entity: str = Field(description="Name of target / seller (e.g. 'CloudScale Technologies, Inc.')")
    closing_date: str = Field(description="Target or actual closing date (e.g. 'August 18, 2026')")
    counsel_firm: str = Field(default="Sullivan & Cromwell LLP", description="Deal firm compiling the binder")
    total_items: int = Field(default=0)
    items: List[ChecklistItem] = Field(default_factory=list)


class MatchResult(BaseModel):
    """Result of semantic matching a document to a checklist item."""
    checklist_item_id: str
    tab_number: int
    doc_id: Optional[str] = None
    matched_filename: Optional[str] = None
    confidence: MatchConfidence = Field(default=MatchConfidence.UNMATCHED)
    score: float = Field(default=0.0, ge=0.0, le=1.0, description="Normalized match score")
    match_reasons: List[str] = Field(default_factory=list, description="Feature breakdown explaining match")
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.MISSING)
    unresolved_flags: List[str] = Field(default_factory=list, description="Discrepancies (e.g. missing buyer signature)")


class TabEntry(BaseModel):
    """Specification for a single tab divider and included document in the PDF Binder."""
    tab_number: int
    tab_label: str
    category: str
    title: str
    document_path: Optional[str] = None
    start_page: int = Field(default=1, description="1-indexed start page in final combined PDF")
    page_count: int = Field(default=1)
    execution_status: ExecutionStatus = Field(default=ExecutionStatus.FULLY_EXECUTED)
    signatories_summary: Optional[str] = None


class BinderSpec(BaseModel):
    """Configuration for assembling the navigable PDF closing binder."""
    deal_title: str
    subtitle: str = "COMPILATION OF EXECUTED TRANSACTION DOCUMENTS"
    buyer_entity: str
    target_entity: str
    closing_date: str
    counsel_firm: str
    include_cover_page: bool = True
    include_table_of_contents: bool = True
    include_tab_dividers: bool = True
    include_running_headers: bool = True
    running_header_title: Optional[str] = None
    tabs: List[TabEntry] = Field(default_factory=list)


class OutstandingItemEntry(BaseModel):
    """An entry in the client-ready Outstanding Items Report."""
    tab_number: int
    tab_label: str
    title: str
    category: str
    status: ExecutionStatus
    responsible_counsel: str
    missing_signatories: List[str] = Field(default_factory=list)
    action_required: str
    priority: PriorityLevel


class OutstandingReport(BaseModel):
    """Client-ready outstanding deficiencies & execution summary."""
    deal_name: str
    generated_at: str
    total_checklist_items: int
    satisfied_count: int
    missing_count: int
    unsigned_count: int
    partially_executed_count: int
    closing_readiness_percentage: float
    is_closing_ready: bool
    missing_items: List[OutstandingItemEntry] = Field(default_factory=list)
    incomplete_items: List[OutstandingItemEntry] = Field(default_factory=list)
    satisfied_items: List[OutstandingItemEntry] = Field(default_factory=list)


class AssemblyResult(BaseModel):
    """Final output artifact paths and closing statistics."""
    deal_name: str
    total_items: int
    matched_count: int
    missing_count: int
    fully_executed_count: int
    partially_executed_count: int
    unsigned_count: int
    readiness_percentage: float
    pdf_binder_path: str
    per_document_folder_path: str
    outstanding_report_pdf_path: str
    outstanding_report_md_path: str
    zip_bundle_path: Optional[str] = None
    assembly_timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
