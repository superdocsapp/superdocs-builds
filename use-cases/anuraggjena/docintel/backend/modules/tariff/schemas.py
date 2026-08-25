from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from backend.core.workflow.stage import WorkflowState
from backend.modules.tariff.memo_types import ProductFacts, RulingFacts


class TariffClaim(BaseModel):
    """A single tariff classification claim"""
    hs_code: str = Field(description="HS tariff code")
    description: str = Field(description="Product description")
    duty_rate: str = Field(description="Applicable duty rate")
    notes: Optional[str] = Field(default=None, description="Additional notes")


class ImpactClaimSummary(BaseModel):
    """Summary of a claim's impact during focused update analysis."""
    claim_id: str
    status: str
    changed_chunk_ids: List[str] = Field(default_factory=list)


class ImpactAnalysisSummary(BaseModel):
    """Focused update impact analysis persisted in workflow state."""
    unchanged_claims: List[ImpactClaimSummary] = Field(default_factory=list)
    affected_claims: List[ImpactClaimSummary] = Field(default_factory=list)


class TariffWorkflowState(WorkflowState):
    """State for tariff classification workflow"""
    # Input
    document_content: Optional[str] = None
    document_id: Optional[str] = None

    # Extract stage output
    extracted_claims: List[TariffClaim] = Field(default_factory=list)
    extract_completed: bool = False

    # Generate stage output
    generated_report: Optional[str] = None
    generate_completed: bool = False

    # Retrieve stage output
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    retrieve_completed: bool = False

    # Claim persistence (from generate stage)
    claim_ids: List[str] = Field(default_factory=list)

    # Citation stage output
    citation_ids: List[str] = Field(default_factory=list)
    citations_completed: bool = False

    # Quality gate
    quality_gate_status: Optional[str] = None
    quality_gate_details: List[Dict[str, Any]] = Field(default_factory=list)
    quality_gate_blocking: bool = False

    # Knowledge transfer
    prior_knowledge: str = ""
    prior_knowledge_entries: List[str] = Field(default_factory=list)
    knowledge_stored: int = 0

    # Focused update support (Phase 7 Priority 4)
    is_focused_update: bool = False
    baseline_run_id: Optional[str] = None
    focused_update_completed: bool = False
    unchanged_claims_count: int = 0
    affected_claims_count: int = 0
    new_chunks_count: int = 0
    contradicted_claims_count: int = 0
    preserved_claim_ids: List[str] = Field(default_factory=list)
    affected_chunk_ids: List[str] = Field(default_factory=list)
    contradictions: List[Dict[str, Any]] = Field(default_factory=list)
    impact_analysis: Optional[ImpactAnalysisSummary] = None
    skip: bool = False
    results_count: int = 0

    # SuperDocs integration (Phase 7)
    superdocs_session_id: Optional[str] = None
    superdocs_document_id: Optional[str] = None
    superdocs_job_id: Optional[str] = None
    superdocs_approval_completed: bool = False
    superdocs_review_id: Optional[str] = None
    superdocs_review_claim_ids: List[str] = Field(default_factory=list)
    superdocs_review_completed: bool = False
    superdocs_approvals_applied: bool = False
    approved_count: int = 0
    rejected_count: int = 0
    final_job_status: Optional[str] = None
    adopted_knowledge_entry_ids: List[str] = Field(default_factory=list)

    # Phase 8: structured memo sections
    product_facts: Optional[ProductFacts] = None
    ruling_facts: List[RulingFacts] = Field(default_factory=list)
    extract_product_completed: bool = False
    extract_ruling_completed: bool = False
    memo_section_ids: List[str] = Field(default_factory=list)
    generated_sections: Dict[str, str] = Field(default_factory=dict)
    generate_memo_completed: bool = False
    sections_to_regenerate: List[str] = Field(default_factory=list)
    preserved_section_ids: List[str] = Field(default_factory=list)
    image_document_ids: List[str] = Field(default_factory=list)
    workspace_document_ids: List[str] = Field(default_factory=list)
    has_ruling_documents: bool = False
    export_completed: bool = False
    export_id: Optional[str] = None

    # Phase 4: Multi-document support
    product_spec_document_ids: List[str] = Field(default_factory=list)
    ruling_document_ids: List[str] = Field(default_factory=list)
    other_document_ids: List[str] = Field(default_factory=list)
    discover_documents_completed: bool = False
    product_spec_content: Optional[str] = None
    ruling_content_map: Dict[str, str] = Field(default_factory=dict)
    matched_ruling_ids: List[str] = Field(default_factory=list)
    reconciliation_completed: bool = False
