/**
 * Mock data for development mode.
 * Enables the UI to be exercised without a running backend.
 * Activated via VITE_MOCK_API=true in .env or environment.
 */
import type {
  QueueItem,
  QueueListResponse,
  RunSummary,
  PipelineProgress,
  DecisionResponse,
} from "@/types/review";

export const MOCK_RUNS: RunSummary[] = [
  {
    id: "run-001",
    status: "running",
    started_at: "2024-06-01T10:00:00Z",
    ended_at: null,
  },
  {
    id: "run-002",
    status: "completed",
    started_at: "2024-05-28T08:30:00Z",
    ended_at: "2024-05-28T09:15:00Z",
  },
  {
    id: "run-003",
    status: "paused",
    started_at: "2024-06-02T14:00:00Z",
    ended_at: null,
  },
];

export const MOCK_QUEUE_ITEMS: QueueItem[] = [
  {
    id: "item-001",
    run_id: "run-001",
    item_type: "finding",
    payload: {
      summary:
        "Potential non-compliance with Section 4.2 capital adequacy requirements",
      details: { severity: "high", rule_id: "CAP-4.2" },
      source_citations: [
        {
          claim_id: "claim-001",
          claim_text: "The institution maintains a capital ratio of 8.5%",
          citation_status: "grounded",
          source_location: {
            page_number: 12,
            section_id: "sec-4.2",
            start_offset: 145,
            end_offset: 210,
            clause_ref: "§4.2.1",
          },
        },
      ],
    },
    status: "pending",
    queued_at: "2024-06-01T10:15:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  },
  {
    id: "item-002",
    run_id: "run-001",
    item_type: "conflict",
    payload: {
      summary:
        "Conflicting statements regarding loan-to-value ratios in sections 3.1 and 5.4",
      details: { severity: "medium", sections: ["3.1", "5.4"] },
      source_citations: [
        {
          claim_id: "claim-002",
          claim_text: "Maximum LTV ratio is 80%",
          citation_status: "grounded",
          source_location: {
            page_number: 8,
            section_id: "sec-3.1",
            start_offset: 50,
            end_offset: 95,
            clause_ref: "§3.1.3",
          },
        },
        {
          claim_id: "claim-003",
          claim_text: "LTV ratios may exceed regulatory thresholds",
          citation_status: "unverifiable",
          source_location: null,
        },
      ],
    },
    status: "pending",
    queued_at: "2024-06-01T10:20:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  },
  {
    id: "item-003",
    run_id: "run-001",
    item_type: "proposed_update",
    payload: {
      summary:
        "Update interest rate disclosure language to match revised regulatory guidance",
      details: { target_section: "6.1", update_type: "language" },
      source_citations: [
        {
          claim_id: "claim-004",
          claim_text: "Interest rates shall be disclosed in APR format",
          citation_status: "grounded",
          source_location: {
            page_number: 22,
            section_id: "sec-6.1",
            start_offset: 0,
            end_offset: 55,
            clause_ref: "§6.1.2",
          },
        },
      ],
    },
    status: "approved",
    queued_at: "2024-06-01T10:05:00Z",
    decided_at: "2024-06-01T11:00:00Z",
    decision: "approved",
    reviewer_id: "reviewer-A",
    justification: "Language aligns with latest regulatory guidance.",
  },
  {
    id: "item-004",
    run_id: "run-001",
    item_type: "finding",
    payload: {
      summary: "Missing disclosure of fee schedule changes effective Q3 2024",
      details: { severity: "low", rule_id: "DISC-7.3" },
      source_citations: [
        {
          claim_id: "claim-005",
          claim_text: "Fee schedules were updated in March 2024",
          citation_status: "unverifiable",
          source_location: null,
        },
        {
          claim_id: "claim-006",
          claim_text:
            "Customers must be notified 30 days prior to fee changes",
          citation_status: "grounded",
          source_location: {
            page_number: 5,
            section_id: "sec-7.3",
            start_offset: 200,
            end_offset: 270,
            clause_ref: null,
          },
        },
      ],
    },
    status: "pending",
    queued_at: "2024-06-01T10:30:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  },
  {
    id: "item-005",
    run_id: "run-001",
    item_type: "conflict",
    payload: {
      summary:
        "Data retention policy conflicts between privacy section and appendix B",
      details: { severity: "high", sections: ["2.4", "appendix-B"] },
      source_citations: [
        {
          claim_id: "claim-007",
          claim_text: "Data retained for 7 years per regulation",
          citation_status: "grounded",
          source_location: {
            page_number: 4,
            section_id: "sec-2.4",
            start_offset: 80,
            end_offset: 130,
            clause_ref: "§2.4.1",
          },
        },
      ],
    },
    status: "rejected",
    queued_at: "2024-06-01T10:10:00Z",
    decided_at: "2024-06-01T11:30:00Z",
    decision: "rejected",
    reviewer_id: "reviewer-B",
    justification:
      "Conflict does not exist — appendix B references archived policy.",
  },
  {
    id: "item-006",
    run_id: "run-001",
    item_type: "proposed_update",
    payload: {
      summary: "Add risk disclosure paragraph to executive summary",
      details: { target_section: "1.0", update_type: "addition" },
      source_citations: [
        {
          claim_id: "claim-008",
          claim_text:
            "Executive summaries must include material risk factors",
          citation_status: "unverifiable",
          source_location: null,
        },
      ],
    },
    status: "pending",
    queued_at: "2024-06-01T10:45:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  },
];

export const MOCK_PROGRESS: PipelineProgress = {
  current_node: "match_rules_against_sources",
  completed_nodes: [
    "ingest",
    "extract_text",
    "classify_document",
    "chunk",
    "embed",
    "extract_claims",
    "match_rules",
  ],
  node_status: "completed",
  run_status: "running",
};

// ─── In-memory state for mock decisions ──────────────────────────────────────

let mockItems = [...MOCK_QUEUE_ITEMS];

export function resetMockState() {
  mockItems = [...MOCK_QUEUE_ITEMS];
}

// ─── Mock API implementations ────────────────────────────────────────────────

export async function mockFetchRuns(): Promise<RunSummary[]> {
  await delay(100);
  return MOCK_RUNS;
}

export async function mockFetchQueue(runId: string): Promise<QueueListResponse> {
  await delay(150);
  const items = mockItems.filter((i) => i.run_id === runId);
  return {
    run_id: runId,
    items,
    total: items.length,
    pending: items.filter((i) => i.status === "pending").length,
  };
}

export async function mockFetchItem(itemId: string): Promise<QueueItem> {
  await delay(80);
  const item = mockItems.find((i) => i.id === itemId);
  if (!item) throw new Error("Item not found");
  return item;
}

export async function mockSubmitDecision(
  itemId: string,
  request: {
    decision: "approved" | "rejected";
    reviewer_id: string;
    justification: string;
  }
): Promise<DecisionResponse> {
  await delay(300);
  const idx = mockItems.findIndex((i) => i.id === itemId);
  if (idx === -1) throw new Error("Item not found");

  mockItems[idx] = {
    ...mockItems[idx],
    status: request.decision,
    decision: request.decision,
    decided_at: new Date().toISOString(),
    reviewer_id: request.reviewer_id,
    justification: request.justification,
  };

  return {
    item_id: itemId,
    decision: request.decision,
    success: true,
    error: null,
  };
}

export async function mockFetchRunProgress(_runId: string): Promise<PipelineProgress> {
  await delay(100);
  return MOCK_PROGRESS;
}

export async function mockResumeRun(_runId: string): Promise<unknown> {
  await delay(200);
  return { status: "running" };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
