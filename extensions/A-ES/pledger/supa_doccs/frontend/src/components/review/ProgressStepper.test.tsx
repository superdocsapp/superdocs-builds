import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ProgressStepper } from "./ProgressStepper";

describe("ProgressStepper", () => {
  it("renders all three stages", () => {
    render(<ProgressStepper completedNodes={[]} currentNode={null} />);

    expect(screen.getByRole("list", { name: "Pipeline progress" })).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
  });

  it("marks a stage as complete when all its nodes are completed", () => {
    const completedNodes = [
      "ingest", "extract_text", "classify_document", "chunk", "embed",
    ];

    render(
      <ProgressStepper completedNodes={completedNodes} currentNode={null} />
    );

    const understandStage = screen.getByLabelText("Stage: Understand - Complete");
    expect(understandStage).toBeInTheDocument();
  });

  it("marks a stage as in-progress when currentNode is within that stage", () => {
    render(
      <ProgressStepper completedNodes={[]} currentNode="extract_claims" />
    );

    const examineStage = screen.getByLabelText("Stage: Examine - In progress");
    expect(examineStage).toBeInTheDocument();
  });

  it("marks a stage as pending when it has not started", () => {
    render(<ProgressStepper completedNodes={[]} currentNode={null} />);

    const stayAliveStage = screen.getByLabelText("Stage: Stay-Alive - Pending");
    expect(stayAliveStage).toBeInTheDocument();
  });

  it("renders checkmark for complete stage", () => {
    const completedNodes = [
      "ingest", "extract_text", "classify_document", "chunk", "embed",
    ];

    const { container } = render(
      <ProgressStepper completedNodes={completedNodes} currentNode={null} />
    );

    // Complete stage uses an SVG checkmark with the draw-check class
    const checkSvg = container.querySelector(".draw-check");
    expect(checkSvg).toBeInTheDocument();
  });

  it("renders animated spinner for in-progress stage", () => {
    const { container } = render(
      <ProgressStepper completedNodes={[]} currentNode="ingest" />
    );

    // In-progress stage uses a conic-spinner class
    const spinner = container.querySelector(".conic-spinner");
    expect(spinner).toBeInTheDocument();
  });

  it("has proper ARIA structure with role list and listitems", () => {
    render(<ProgressStepper completedNodes={[]} currentNode={null} />);

    const list = screen.getByRole("list", { name: "Pipeline progress" });
    expect(list).toBeInTheDocument();

    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveAttribute("aria-label", expect.stringContaining("Understand"));
    expect(items[1]).toHaveAttribute("aria-label", expect.stringContaining("Examine"));
    expect(items[2]).toHaveAttribute("aria-label", expect.stringContaining("Stay-Alive"));
  });

  it("shows all stages complete when entire pipeline has finished", () => {
    const allNodes = [
      "ingest", "extract_text", "classify_document", "chunk", "embed",
      "extract_claims", "match_rules", "match_rules_against_sources", "merge_findings", "score_confidence",
      "route_to_queue", "human_review", "finalize",
    ];

    render(
      <ProgressStepper completedNodes={allNodes} currentNode={null} />
    );

    expect(screen.getByLabelText("Stage: Understand - Complete")).toBeInTheDocument();
    expect(screen.getByLabelText("Stage: Examine - Complete")).toBeInTheDocument();
    expect(screen.getByLabelText("Stage: Stay-Alive - Complete")).toBeInTheDocument();
  });
});
