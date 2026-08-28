import { render, screen, fireEvent, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { Toast } from "./Toast";

describe("Toast", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when visible is false", () => {
    const { container } = render(
      <Toast message="Test" visible={false} onDismiss={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the message when visible is true", () => {
    render(
      <Toast message="Item was already decided" visible={true} onDismiss={vi.fn()} />
    );
    expect(screen.getByText("Item was already decided")).toBeInTheDocument();
  });

  it('has role="status" for polite screen reader announcement', () => {
    render(
      <Toast message="Test" visible={true} onDismiss={vi.fn()} />
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it('has aria-live="polite"', () => {
    render(
      <Toast message="Test" visible={true} onDismiss={vi.fn()} />
    );
    const toast = screen.getByRole("status");
    expect(toast).toHaveAttribute("aria-live", "polite");
  });

  it("auto-dismisses after the specified duration", () => {
    const onDismiss = vi.fn();
    render(
      <Toast message="Test" visible={true} onDismiss={onDismiss} duration={3000} />
    );

    expect(screen.getByText("Test")).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(3000);
    });

    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("auto-dismisses after default 4000ms when no duration specified", () => {
    const onDismiss = vi.fn();
    render(
      <Toast message="Test" visible={true} onDismiss={onDismiss} />
    );

    act(() => {
      vi.advanceTimersByTime(3999);
    });
    expect(onDismiss).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("calls onDismiss when dismiss button is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <Toast message="Test" visible={true} onDismiss={onDismiss} />
    );

    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("hides the toast after dismiss button click", () => {
    const onDismiss = vi.fn();
    const { container } = render(
      <Toast message="Test" visible={true} onDismiss={onDismiss} />
    );

    fireEvent.click(screen.getByLabelText("Dismiss notification"));
    expect(container.querySelector('[role="status"]')).toBeNull();
  });

  it("applies info variant styling by default", () => {
    render(
      <Toast message="Test" visible={true} onDismiss={vi.fn()} />
    );
    const toast = screen.getByRole("status");
    expect(toast.className).toContain("border-indigo-500/20");
    expect(toast.className).toContain("text-indigo-200");
  });

  it("applies error variant styling", () => {
    render(
      <Toast message="Test" visible={true} onDismiss={vi.fn()} variant="error" />
    );
    const toast = screen.getByRole("status");
    expect(toast.className).toContain("border-rose-500/20");
    expect(toast.className).toContain("text-rose-200");
  });

  it("applies warning variant styling", () => {
    render(
      <Toast message="Test" visible={true} onDismiss={vi.fn()} variant="warning" />
    );
    const toast = screen.getByRole("status");
    expect(toast.className).toContain("border-amber-500/20");
    expect(toast.className).toContain("text-amber-200");
  });

  it("displays 409 conflict message correctly", () => {
    render(
      <Toast
        message="This item was already decided by another reviewer"
        visible={true}
        onDismiss={vi.fn()}
        variant="warning"
      />
    );
    expect(
      screen.getByText("This item was already decided by another reviewer")
    ).toBeInTheDocument();
  });
});
