import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { RunSelector } from "./RunSelector";
import type { RunSummary } from "@/types/review";

const mockRuns: RunSummary[] = [
  {
    id: "run-abcdef12",
    status: "running",
    started_at: "2024-01-15T10:30:00Z",
    ended_at: null,
  },
  {
    id: "run-98765432",
    status: "completed",
    started_at: "2024-01-14T08:00:00Z",
    ended_at: "2024-01-14T09:00:00Z",
  },
  {
    id: "run-failtest",
    status: "failed",
    started_at: "2024-01-13T12:00:00Z",
    ended_at: "2024-01-13T12:05:00Z",
  },
];

describe("RunSelector", () => {
  it("renders with the ARIA label 'Select pipeline run'", () => {
    render(
      <RunSelector runs={mockRuns} selectedRunId={null} onSelectRun={() => {}} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    expect(trigger).toBeInTheDocument();
  });

  it("shows placeholder text when no run is selected", () => {
    render(
      <RunSelector runs={mockRuns} selectedRunId={null} onSelectRun={() => {}} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    expect(trigger).toHaveTextContent("Select a run");
  });

  it("displays the selected run ID (truncated) when a run is selected", () => {
    render(
      <RunSelector
        runs={mockRuns}
        selectedRunId="run-abcdef12"
        onSelectRun={() => {}}
      />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    expect(trigger).toHaveTextContent("run-abcd");
  });

  it("shows run options when opened", async () => {
    const user = userEvent.setup();

    render(
      <RunSelector runs={mockRuns} selectedRunId={null} onSelectRun={() => {}} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    await user.click(trigger);

    // Radix Select renders options in a portal attached to document.body
    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    expect(options).toHaveLength(3);
  });

  it("calls onSelectRun when a run is selected", async () => {
    const onSelectRun = vi.fn();
    const user = userEvent.setup();

    render(
      <RunSelector runs={mockRuns} selectedRunId={null} onSelectRun={onSelectRun} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    await user.click(trigger);

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");
    await user.click(options[1]);

    expect(onSelectRun).toHaveBeenCalledWith("run-98765432");
  });

  it("renders status indicator dots for each run option", async () => {
    const user = userEvent.setup();

    render(
      <RunSelector runs={mockRuns} selectedRunId={null} onSelectRun={() => {}} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    await user.click(trigger);

    const listbox = screen.getByRole("listbox");
    const options = within(listbox).getAllByRole("option");

    // Running status -> blue dot
    const runningDot = options[0].querySelector("[aria-hidden='true']");
    expect(runningDot).toBeInTheDocument();
    expect(runningDot!.className).toContain("bg-blue-400");

    // Completed status -> emerald dot
    const completedDot = options[1].querySelector("[aria-hidden='true']");
    expect(completedDot!.className).toContain("bg-emerald-400");

    // Failed status -> rose dot
    const failedDot = options[2].querySelector("[aria-hidden='true']");
    expect(failedDot!.className).toContain("bg-rose-400");
  });

  it("renders with an empty runs array", () => {
    render(
      <RunSelector runs={[]} selectedRunId={null} onSelectRun={() => {}} />
    );

    const trigger = screen.getByRole("combobox", { name: "Select pipeline run" });
    expect(trigger).toBeInTheDocument();
    expect(trigger).toHaveTextContent("Select a run");
  });
});
