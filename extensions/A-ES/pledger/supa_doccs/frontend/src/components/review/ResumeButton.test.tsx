import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ResumeButton } from "./ResumeButton";

describe("ResumeButton", () => {
  it("renders nothing when canResume is false", () => {
    const { container } = render(
      <ResumeButton canResume={false} isResuming={false} onResume={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the button when canResume is true", () => {
    render(
      <ResumeButton canResume={true} isResuming={false} onResume={vi.fn()} />
    );
    expect(
      screen.getByRole("button", { name: "Resume pipeline run" })
    ).toBeInTheDocument();
  });

  it("displays 'Resume' text when not resuming", () => {
    render(
      <ResumeButton canResume={true} isResuming={false} onResume={vi.fn()} />
    );
    expect(screen.getByText("Resume")).toBeInTheDocument();
  });

  it("displays 'Resuming…' text when resuming", () => {
    render(
      <ResumeButton canResume={true} isResuming={true} onResume={vi.fn()} />
    );
    expect(screen.getByText("Resuming…")).toBeInTheDocument();
  });

  it("is disabled while resuming", () => {
    render(
      <ResumeButton canResume={true} isResuming={true} onResume={vi.fn()} />
    );
    const button = screen.getByRole("button", { name: "Resume pipeline run" });
    expect(button).toBeDisabled();
  });

  it("calls onResume when clicked", () => {
    const onResume = vi.fn();
    render(
      <ResumeButton canResume={true} isResuming={false} onResume={onResume} />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Resume pipeline run" })
    );
    expect(onResume).toHaveBeenCalledTimes(1);
  });

  it("does not call onResume when disabled", () => {
    const onResume = vi.fn();
    render(
      <ResumeButton canResume={true} isResuming={true} onResume={onResume} />
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Resume pipeline run" })
    );
    expect(onResume).not.toHaveBeenCalled();
  });

  it("has aria-busy=true when resuming", () => {
    render(
      <ResumeButton canResume={true} isResuming={true} onResume={vi.fn()} />
    );
    const button = screen.getByRole("button", { name: "Resume pipeline run" });
    expect(button).toHaveAttribute("aria-busy", "true");
  });

  it("has aria-busy=false when not resuming", () => {
    render(
      <ResumeButton canResume={true} isResuming={false} onResume={vi.fn()} />
    );
    const button = screen.getByRole("button", { name: "Resume pipeline run" });
    expect(button).toHaveAttribute("aria-busy", "false");
  });
});
