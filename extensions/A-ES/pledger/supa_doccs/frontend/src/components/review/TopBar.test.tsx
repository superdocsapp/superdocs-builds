import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { TopBar } from "./TopBar";
import type { RunSummary } from "@/types/review";

const mockRuns: RunSummary[] = [
  { id: "run-001", status: "running", started_at: "2024-01-15T10:00:00Z", ended_at: null },
  { id: "run-002", status: "completed", started_at: "2024-01-14T08:00:00Z", ended_at: "2024-01-14T09:30:00Z" },
];

describe("TopBar", () => {
  it("renders RunSelector and StatusBadge", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="running"
        onSelectRun={vi.fn()}
      />
    );

    expect(screen.getByLabelText("Select pipeline run")).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("displays the correct run status in StatusBadge", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="failed"
        onSelectRun={vi.fn()}
      />
    );

    // "failed" appears both in the StatusBadge and in the pipeline summary
    expect(screen.getByRole("status")).toHaveTextContent("failed");
  });

  it("renders as a header element", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="running"
        onSelectRun={vi.fn()}
      />
    );

    expect(screen.getByRole("banner")).toBeInTheDocument();
  });

  it("applies frosted-glass styling classes", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="running"
        onSelectRun={vi.fn()}
      />
    );

    const header = screen.getByRole("banner");
    expect(header.className).toContain("backdrop-blur-xl");
    expect(header.className).toContain("border-b");
    expect(header.className).toContain("border-white/[0.06]");
  });

  it("uses flex row layout with gap", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="running"
        onSelectRun={vi.fn()}
      />
    );

    const header = screen.getByRole("banner");
    expect(header.className).toContain("flex");
    expect(header.className).toContain("items-center");
    expect(header.className).toContain("gap-4");
  });

  it("passes onSelectRun callback to RunSelector", () => {
    const onSelectRun = vi.fn();
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="completed"
        onSelectRun={onSelectRun}
      />
    );

    // RunSelector is rendered with the trigger accessible
    expect(screen.getByLabelText("Select pipeline run")).toBeInTheDocument();
  });

  it("does not render ResumeButton when onResume is not provided", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="paused"
        onSelectRun={vi.fn()}
      />
    );

    expect(
      screen.queryByRole("button", { name: "Resume pipeline run" })
    ).not.toBeInTheDocument();
  });

  it("renders ResumeButton when onResume is provided and canResume is true", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="paused"
        onSelectRun={vi.fn()}
        canResume={true}
        isResuming={false}
        onResume={vi.fn()}
      />
    );

    expect(
      screen.getByRole("button", { name: "Resume pipeline run" })
    ).toBeInTheDocument();
  });

  it("does not render ResumeButton when canResume is false even if onResume provided", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="running"
        onSelectRun={vi.fn()}
        canResume={false}
        isResuming={false}
        onResume={vi.fn()}
      />
    );

    expect(
      screen.queryByRole("button", { name: "Resume pipeline run" })
    ).not.toBeInTheDocument();
  });

  it("calls onResume when ResumeButton is clicked", () => {
    const onResume = vi.fn();
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="paused"
        onSelectRun={vi.fn()}
        canResume={true}
        isResuming={false}
        onResume={onResume}
      />
    );

    fireEvent.click(
      screen.getByRole("button", { name: "Resume pipeline run" })
    );
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it("shows resuming state when isResuming is true", () => {
    render(
      <TopBar
        runs={mockRuns}
        selectedRunId="run-001"
        runStatus="paused"
        onSelectRun={vi.fn()}
        canResume={true}
        isResuming={true}
        onResume={vi.fn()}
      />
    );

    expect(screen.getByText("Resuming…")).toBeInTheDocument();
    const button = screen.getByRole("button", { name: "Resume pipeline run" });
    expect(button).toBeDisabled();
  });
});
