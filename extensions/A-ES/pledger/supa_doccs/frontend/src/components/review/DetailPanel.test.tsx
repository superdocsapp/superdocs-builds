import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DetailPanel } from "./DetailPanel";
import type { QueueItem } from "@/types/review";

const mockItem: QueueItem = {
  id: "item-1",
  run_id: "run-1",
  item_type: "finding",
  payload: {
    summary: "Potential compliance violation in section 4.2",
    details: {
      severity: "high",
      rule_id: "MF-001",
    },
    source_citations: [
      {
        claim_id: "claim-1",
        claim_text: "Interest rate exceeds regulatory cap",
        citation_status: "grounded",
        source_location: {
          page_number: 12,
          section_id: "4.2",
          start_offset: 100,
          end_offset: 200,
          clause_ref: "§4.2.1",
        },
      },
      {
        claim_id: "claim-2",
        claim_text: "Disclosure not found",
        citation_status: "unverifiable",
        source_location: null,
      },
    ],
  },
  status: "pending",
  queued_at: "2024-01-15T10:30:00Z",
  decided_at: null,
  decision: null,
  reviewer_id: null,
  justification: null,
};

describe("DetailPanel", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders placeholder when item is null", () => {
    render(
      <DetailPanel item={null} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByText("Select an item to review")).toBeInTheDocument();
  });

  it("renders PayloadView with item summary as heading", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(
      screen.getByText("Potential compliance violation in section 4.2")
    ).toBeInTheDocument();
  });

  it("renders item_type badge and status", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByText("FINDING")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
  });

  it("renders CitationList with correct count header", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByText("Source Citations (2)")).toBeInTheDocument();
  });

  it("renders CitationChips for each citation", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    // Grounded citation renders clause_ref (use aria-label to disambiguate from table cell)
    expect(
      screen.getByLabelText("Citation grounded: §4.2.1")
    ).toBeInTheDocument();
    // Unverifiable citation renders placeholder
    expect(
      screen.getByText("[citation unverifiable]")
    ).toBeInTheDocument();
  });

  it("renders SourceLocationTable for citations with source_location", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    // Table headers
    expect(screen.getByText("Page")).toBeInTheDocument();
    expect(screen.getByText("Section")).toBeInTheDocument();
    expect(screen.getByText("Clause Ref")).toBeInTheDocument();
    expect(screen.getByText("Offset Range")).toBeInTheDocument();

    // Row data for grounded citation
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("4.2")).toBeInTheDocument();
    expect(screen.getAllByText("§4.2.1").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("100–200")).toBeInTheDocument();
  });

  // Prompt 4.3: the reviewer must see the method that actually ran —
  // a deterministic rule finding arrives labeled "structured" (from the
  // enqueue-time resolver) and must render as such, not as "llm".
  it("renders evaluation_method: structured for a deterministic rule finding", () => {
    const structuredItem: QueueItem = {
      ...mockItem,
      payload: {
        ...mockItem.payload,
        details: {
          claim_id: "loan_agreement.apr_1",
          rule_id: "USURY-36.1",
          severity: "high",
          evaluation_method: "structured",
        },
      },
    };
    render(
      <DetailPanel item={structuredItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByText("evaluation_method:")).toBeInTheDocument();
    expect(screen.getByText("structured")).toBeInTheDocument();
    expect(screen.queryByText("llm")).not.toBeInTheDocument();
  });

  it("renders DecisionControls with approve/reject buttons for pending items", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(
      screen.getByRole("button", { name: /approve/i })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /reject/i })
    ).toBeInTheDocument();
  });

  it("hides decision buttons for non-pending items", () => {
    const decidedItem: QueueItem = {
      ...mockItem,
      status: "approved",
      decision: "approved",
      decided_at: "2024-01-15T11:00:00Z",
    };

    render(
      <DetailPanel item={decidedItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(
      screen.queryByRole("button", { name: /approve/i })
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /reject/i })
    ).not.toBeInTheDocument();
  });

  it("disables submit buttons when justification is empty", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
  });

  it("enables submit buttons when justification is provided", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    const textarea = screen.getByLabelText("Decision justification");
    fireEvent.change(textarea, { target: { value: "Reviewed and confirmed" } });

    expect(screen.getByRole("button", { name: /approve/i })).toBeEnabled();
    expect(screen.getByRole("button", { name: /reject/i })).toBeEnabled();
  });

  it("calls onDecide with correct args when approve is clicked", () => {
    const onDecide = vi.fn();

    render(
      <DetailPanel item={mockItem} onDecide={onDecide} isSubmitting={false} />
    );

    const textarea = screen.getByLabelText("Decision justification");
    fireEvent.change(textarea, { target: { value: "Looks good" } });
    fireEvent.click(screen.getByRole("button", { name: /approve/i }));

    // Wait for sweep animation timeout
    act(() => { vi.advanceTimersByTime(400); });

    expect(onDecide).toHaveBeenCalledWith("approved", "Looks good");
  });

  it("renders details key-value pairs from payload", () => {
    render(
      <DetailPanel item={mockItem} onDecide={vi.fn()} isSubmitting={false} />
    );

    expect(screen.getByText("severity:")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByText("rule_id:")).toBeInTheDocument();
    expect(screen.getByText("MF-001")).toBeInTheDocument();
  });
});
