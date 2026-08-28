import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { DecisionControls } from "./DecisionControls";
import { QueueItem } from "@/types/review";

function makePendingItem(overrides: Partial<QueueItem> = {}): QueueItem {
  return {
    id: "item-1",
    run_id: "run-1",
    item_type: "finding",
    payload: {
      summary: "Test finding",
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

function makeDecidedItem(
  decision: "approved" | "rejected"
): QueueItem {
  return makePendingItem({
    status: decision,
    decision,
    decided_at: "2024-01-01T01:00:00Z",
    reviewer_id: "reviewer-1",
    justification: "Already decided",
  });
}

describe("DecisionControls", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe("when item is pending", () => {
    it("renders Approve and Reject buttons", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /reject/i })).toBeInTheDocument();
    });

    it("renders justification textarea with proper aria-label", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      expect(textarea).toBeInTheDocument();
      expect(textarea.tagName).toBe("TEXTAREA");
    });

    it("disables buttons when justification is empty", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    });

    it("disables buttons when justification is only whitespace", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      fireEvent.change(textarea, { target: { value: "   " } });

      expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    });

    it("enables buttons when justification has non-whitespace text", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      fireEvent.change(textarea, { target: { value: "Looks good" } });

      expect(screen.getByRole("button", { name: /approve/i })).toBeEnabled();
      expect(screen.getByRole("button", { name: /reject/i })).toBeEnabled();
    });

    it("calls onDecide with 'approved' and trimmed justification on Approve click", () => {
      const onDecide = vi.fn();
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={onDecide}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      fireEvent.change(textarea, { target: { value: "  Confirmed valid  " } });
      fireEvent.click(screen.getByRole("button", { name: /approve/i }));

      // Wait for sweep animation timeout
      act(() => { vi.advanceTimersByTime(400); });

      expect(onDecide).toHaveBeenCalledWith("approved", "Confirmed valid");
    });

    it("calls onDecide with 'rejected' and trimmed justification on Reject click", () => {
      const onDecide = vi.fn();
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={onDecide}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      fireEvent.change(textarea, { target: { value: "Non-compliant" } });
      fireEvent.click(screen.getByRole("button", { name: /reject/i }));

      // Wait for sweep animation timeout
      act(() => { vi.advanceTimersByTime(400); });

      expect(onDecide).toHaveBeenCalledWith("rejected", "Non-compliant");
    });

    it("clears the textarea after submitting a decision", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      const textarea = screen.getByLabelText("Decision justification") as HTMLTextAreaElement;
      fireEvent.change(textarea, { target: { value: "Valid" } });
      fireEvent.click(screen.getByRole("button", { name: /approve/i }));

      // Wait for sweep animation timeout
      act(() => { vi.advanceTimersByTime(400); });

      expect(textarea.value).toBe("");
    });

    it("disables buttons while isSubmitting is true", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={true}
        />
      );

      expect(screen.getByRole("button", { name: /approve/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /reject/i })).toBeDisabled();
    });

    it("shows loading spinners when isSubmitting", () => {
      const { container } = render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={true}
        />
      );

      const spinners = container.querySelectorAll("svg.animate-spin");
      expect(spinners.length).toBe(2);
    });

    it("disables the textarea while isSubmitting", () => {
      render(
        <DecisionControls
          item={makePendingItem()}
          onDecide={vi.fn()}
          isSubmitting={true}
        />
      );

      const textarea = screen.getByLabelText("Decision justification");
      expect(textarea).toBeDisabled();
    });
  });

  describe("when item is not pending", () => {
    it("does not show Approve or Reject buttons for approved items", () => {
      render(
        <DecisionControls
          item={makeDecidedItem("approved")}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /reject/i })).not.toBeInTheDocument();
    });

    it("does not show Approve or Reject buttons for rejected items", () => {
      render(
        <DecisionControls
          item={makeDecidedItem("rejected")}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /reject/i })).not.toBeInTheDocument();
    });

    it("displays the decision for approved items", () => {
      render(
        <DecisionControls
          item={makeDecidedItem("approved")}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.getByText("approved")).toBeInTheDocument();
    });

    it("displays the decision for rejected items", () => {
      render(
        <DecisionControls
          item={makeDecidedItem("rejected")}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.getByText("rejected")).toBeInTheDocument();
    });

    it("does not render the justification textarea", () => {
      render(
        <DecisionControls
          item={makeDecidedItem("approved")}
          onDecide={vi.fn()}
          isSubmitting={false}
        />
      );

      expect(screen.queryByLabelText("Decision justification")).not.toBeInTheDocument();
    });
  });
});
