import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueueSummaryBar } from "./QueueSummaryBar";

describe("QueueSummaryBar", () => {
  it("displays pending and decided counts", () => {
    render(<QueueSummaryBar total={10} pending={4} />);
    expect(screen.getByText("4 pending")).toBeInTheDocument();
    expect(screen.getByText("6 decided")).toBeInTheDocument();
    expect(screen.getByText("10 total")).toBeInTheDocument();
  });

  it("displays zero counts correctly", () => {
    render(<QueueSummaryBar total={0} pending={0} />);
    expect(screen.getByText("0 pending")).toBeInTheDocument();
    expect(screen.getByText("0 decided")).toBeInTheDocument();
    expect(screen.getByText("0 total")).toBeInTheDocument();
  });

  it("has aria-live=polite for screen reader updates", () => {
    const { container } = render(<QueueSummaryBar total={5} pending={2} />);
    const bar = container.firstElementChild;
    expect(bar).toHaveAttribute("aria-live", "polite");
  });
});
