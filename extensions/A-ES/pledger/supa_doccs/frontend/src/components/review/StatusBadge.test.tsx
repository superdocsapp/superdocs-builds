import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  const statuses = ["running", "completed", "failed", "paused"] as const;

  it.each(statuses)("renders %s status with correct ARIA attributes", (status) => {
    render(<StatusBadge status={status} />);

    const badge = screen.getByRole("status");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute("aria-label", `Run status: ${status}`);
    expect(badge).toHaveTextContent(status);
  });

  it("applies blue color classes for running status", () => {
    render(<StatusBadge status="running" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("bg-blue-500/10");
    expect(badge.className).toContain("text-blue-300");
    expect(badge.className).toContain("border-blue-500/20");
  });

  it("applies green color classes for completed status", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("bg-emerald-500/10");
    expect(badge.className).toContain("text-emerald-300");
    expect(badge.className).toContain("border-emerald-500/20");
  });

  it("applies red color classes for failed status", () => {
    render(<StatusBadge status="failed" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("bg-rose-500/10");
    expect(badge.className).toContain("text-rose-300");
    expect(badge.className).toContain("border-rose-500/20");
  });

  it("applies amber color classes for paused status", () => {
    render(<StatusBadge status="paused" />);
    const badge = screen.getByRole("status");
    expect(badge.className).toContain("bg-amber-500/10");
    expect(badge.className).toContain("text-amber-300");
    expect(badge.className).toContain("border-amber-500/20");
  });

  it("renders as a span element with pill styling", () => {
    render(<StatusBadge status="running" />);
    const badge = screen.getByRole("status");
    expect(badge.tagName).toBe("SPAN");
    expect(badge.className).toContain("rounded-full");
    expect(badge.className).toContain("border");
  });

  it("includes a status indicator dot", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByRole("status");
    const dot = badge.querySelector("[aria-hidden='true']");
    expect(dot).toBeInTheDocument();
    expect(dot!.className).toContain("rounded-full");
    expect(dot!.className).toContain("bg-emerald-400");
  });

  it("applies animate-pulse to the dot for running status", () => {
    render(<StatusBadge status="running" />);
    const badge = screen.getByRole("status");
    const dot = badge.querySelector("[aria-hidden='true']");
    expect(dot!.className).toContain("animate-pulse");
  });

  it("does not animate the dot for non-running statuses", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByRole("status");
    const dot = badge.querySelector("[aria-hidden='true']");
    expect(dot!.className).not.toContain("animate-pulse");
  });
});
