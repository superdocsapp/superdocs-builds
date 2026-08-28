import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ProvenancePanel } from "./ProvenancePanel";
import type { QueueItem } from "@/types/review";

function makeItem(details: Record<string, unknown>): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Finding with provenance",
      details,
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-01T00:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
  };
}

describe("ProvenancePanel", () => {
  it("renders confidence vs threshold, escalation reason, retries and rule text", () => {
    render(
      <ProvenancePanel
        item={makeItem({
          claim_id: "claim-1",
          rule_id: "USURY-36.1",
          confidence: 0.55,
          confidence_threshold: 0.7,
          escalation_reason: "low_confidence",
          retries: { extract_claims: 2, extract_text: 0 },
          playbook_id: "microfinance_v1",
          rule_description: "APR must not exceed 36%",
          rule_check_description: "Check if the stated APR exceeds 36%.",
        })}
      />
    );

    // Confidence compared to the threshold it was judged against
    expect(screen.getByText(/0\.55/)).toBeInTheDocument();
    expect(screen.getByText(/threshold 0\.70/)).toBeInTheDocument();
    expect(screen.getByText("below threshold")).toBeInTheDocument();

    // Human-readable escalation reason
    expect(screen.getByText("Low confidence")).toBeInTheDocument();

    // Retry counts (zero-retry nodes suppressed)
    expect(screen.getByText(/extract_claims ×2/)).toBeInTheDocument();
    expect(screen.queryByText(/extract_text/)).not.toBeInTheDocument();

    // Actual rule text, not just the rule id
    expect(screen.getByText("APR must not exceed 36%")).toBeInTheDocument();
    expect(
      screen.getByText("Check if the stated APR exceeds 36%.")
    ).toBeInTheDocument();
  });

  it("renders nothing when no provenance fields are present", () => {
    const { container } = render(<ProvenancePanel item={makeItem({})} />);
    expect(container).toBeEmptyDOMElement();
  });
});
