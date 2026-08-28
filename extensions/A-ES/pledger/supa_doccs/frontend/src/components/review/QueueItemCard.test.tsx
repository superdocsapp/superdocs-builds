import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueueItemCard } from "./QueueItemCard";
import { QueueItem } from "@/types/review";

function makeItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Short summary text",
      details: {},
      source_citations: [],
    },
    status: "pending",
    queued_at: "2024-01-01T00:00:00Z",
    decided_at: null,
    decision: null,
    reviewer_id: null,
    justification: null,
    ...overrides,
  };
}

describe("QueueItemCard", () => {
  it("renders item_type badge as uppercase", () => {
    render(
      <QueueItemCard
        item={makeItem({ item_type: "conflict" })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByText("CONFLICT")).toBeInTheDocument();
  });

  it("renders payload summary truncated to 80 chars with ellipsis", () => {
    const longSummary = "a".repeat(100);
    render(
      <QueueItemCard
        item={makeItem({
          payload: { summary: longSummary, details: {}, source_citations: [] },
        })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    const expected = "a".repeat(80) + "…";
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("renders full summary when <= 80 chars", () => {
    const shortSummary = "Hello world";
    render(
      <QueueItemCard
        item={makeItem({
          payload: { summary: shortSummary, details: {}, source_citations: [] },
        })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByText(shortSummary)).toBeInTheDocument();
  });

  it("renders status chip with correct text", () => {
    render(
      <QueueItemCard
        item={makeItem({ status: "approved" })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByText("approved")).toBeInTheDocument();
  });

  it("applies aria-selected when isSelected is true", () => {
    render(
      <QueueItemCard
        item={makeItem()}
        isSelected={true}
        isLoading={false}
        onClick={() => {}}
      />
    );
    const option = screen.getByRole("option");
    expect(option).toHaveAttribute("aria-selected", "true");
  });

  it("applies aria-busy when isLoading is true", () => {
    render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={true}
        onClick={() => {}}
      />
    );
    const option = screen.getByRole("option");
    expect(option).toHaveAttribute("aria-busy", "true");
  });

  it("has role=option", () => {
    render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByRole("option")).toBeInTheDocument();
  });

  it("calls onClick when clicked", () => {
    const handleClick = vi.fn();
    render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={false}
        onClick={handleClick}
      />
    );
    fireEvent.click(screen.getByRole("option"));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("calls onClick on Enter key", () => {
    const handleClick = vi.fn();
    render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={false}
        onClick={handleClick}
      />
    );
    fireEvent.keyDown(screen.getByRole("option"), { key: "Enter" });
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("shows loading spinner when isLoading is true", () => {
    const { container } = render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={true}
        onClick={() => {}}
      />
    );
    const spinner = container.querySelector("svg.animate-spin");
    expect(spinner).toBeInTheDocument();
  });

  it("does not show loading spinner when isLoading is false", () => {
    const { container } = render(
      <QueueItemCard
        item={makeItem()}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    const spinner = container.querySelector("svg.animate-spin");
    expect(spinner).not.toBeInTheDocument();
  });

  it("renders proposed_update as UPDATE badge", () => {
    render(
      <QueueItemCard
        item={makeItem({ item_type: "proposed_update" })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.getByText("UPDATE")).toBeInTheDocument();
  });

  // Regression: run eef332ea item 4a705e77 was approved with zero citations
  // and rendered no unverifiable marker. The empty-array case specifically.
  it("shows the unverifiable marker for citations: [] (empty array)", () => {
    render(
      <QueueItemCard
        item={makeItem({
          payload: { summary: "No citations at all", details: {}, source_citations: [] },
        })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    const marker = screen.getByTitle("Has unverifiable citations");
    expect(marker).toBeInTheDocument();
    expect(marker).toHaveClass("warning-pulse");
  });

  it("hides the unverifiable marker when all citations are grounded with spans", () => {
    render(
      <QueueItemCard
        item={makeItem({
          payload: {
            summary: "Grounded",
            details: {},
            source_citations: [
              {
                claim_id: "c1",
                claim_text: "Grounded claim",
                citation_status: "grounded",
                source_location: {
                  page_number: 1,
                  section_id: "s1",
                  start_offset: 0,
                  end_offset: 10,
                  clause_ref: null,
                },
              },
            ],
          },
        })}
        isSelected={false}
        isLoading={false}
        onClick={() => {}}
      />
    );
    expect(screen.queryByTitle("Has unverifiable citations")).not.toBeInTheDocument();
  });
});
