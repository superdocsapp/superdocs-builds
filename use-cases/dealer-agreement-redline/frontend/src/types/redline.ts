export type Classification = "PRE-APPROVED" | "ESCALATE" | "REFUSE";

export type FindingDecision = "pending" | "approve" | "reject";

export type ReviewStatus = "pending" | "in_review" | "completed" | "applied";

export interface AgreementSection {
    section: string;
    text: string;
}

export interface Deviation {
    section: string;
    master_text: string;
    dealer_text: string;
    deviation_type: string;
    similarity: number;
    classification: Classification;
    reason: string;
    counter_position: string;
}

export interface ReviewSummary {
    total: number;
    pre_approved: number;
    escalate: number;
    refuse: number;
}

export interface AnalyzeResponse {
    review_id: string;
    session_id: string;

    dealer_document?: {
        html: string;
        session_id: string;
        filename: string;
        chunks_count: number;
        version_id: string;
        document_id: string;
    };

    master_attachment?: {
        job_id: string;
        filename: string;
        status: string;
        message: string;
    };

    playbook_attachment?: {
        job_id: string;
        filename: string;
        status: string;
        message: string;
    };

    master_sections: AgreementSection[];
    dealer_sections: AgreementSection[];
    playbook_sections: AgreementSection[];
    deviations: Deviation[];
    summary: ReviewSummary;
}

export interface RedlineFinding extends Deviation {
    id: string;
    decision: FindingDecision;
}

export interface RedlineReview {
    review_id: string;
    session_id: string;
    status: ReviewStatus;
    created_at: string;
    updated_at: string;
    findings: RedlineFinding[];
}

export interface FindingDecisionRequest {
    decision: "approve" | "reject";
}

export interface FindingDecisionResponse {
    review_id: string;
    finding_id: string;
    decision: FindingDecision;
    review_status: ReviewStatus;
    remaining_findings: number;
}

export interface ApplyReviewResponse {
    review_id: string;
    status: "applied";
    applied: boolean;
    chat_response?: {
        response?: string;
        session_id?: string;
        document_changes?: {
            updated_html?: string;
            version_id?: string;
            changes_summary?: string;
            requires_approval?: boolean | null;
            pending_changes?: unknown;
            changes?: unknown[];
            chunk_diffs?: unknown;
            concurrent_merges?: unknown;
            focused_document_id?: string;
        };
        usage?: {
            ops_charged?: number;
            monthly_used?: number;
            monthly_remaining?: number;
        };
    };
}

export interface ApiError {
    detail: string;
}
