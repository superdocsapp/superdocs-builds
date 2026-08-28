import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { ConnectionLostBanner } from "./ConnectionLostBanner";

describe("ConnectionLostBanner", () => {
  it("renders nothing when connectionLost is false", () => {
    const { container } = render(
      <ConnectionLostBanner connectionLost={false} />
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders the warning banner when connectionLost is true", () => {
    render(<ConnectionLostBanner connectionLost={true} />);
    expect(
      screen.getByText("Connection lost. Data may be stale. Retrying...")
    ).toBeInTheDocument();
  });

  it('has role="alert" for screen reader announcement', () => {
    render(<ConnectionLostBanner connectionLost={true} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it('has aria-live="assertive" for immediate announcement', () => {
    render(<ConnectionLostBanner connectionLost={true} />);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveAttribute("aria-live", "assertive");
  });

  it("does not render dismiss button when onDismiss is not provided", () => {
    render(<ConnectionLostBanner connectionLost={true} />);
    expect(
      screen.queryByLabelText("Dismiss connection warning")
    ).not.toBeInTheDocument();
  });

  it("renders dismiss button when onDismiss is provided", () => {
    const onDismiss = vi.fn();
    render(
      <ConnectionLostBanner connectionLost={true} onDismiss={onDismiss} />
    );
    expect(
      screen.getByLabelText("Dismiss connection warning")
    ).toBeInTheDocument();
  });

  it("calls onDismiss when dismiss button is clicked", () => {
    const onDismiss = vi.fn();
    render(
      <ConnectionLostBanner connectionLost={true} onDismiss={onDismiss} />
    );
    fireEvent.click(screen.getByLabelText("Dismiss connection warning"));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });

  it("applies amber/warning styling classes", () => {
    render(<ConnectionLostBanner connectionLost={true} />);
    const banner = screen.getByRole("alert");
    expect(banner.className).toContain("backdrop-blur-xl");
    expect(banner.className).toContain("border-amber-500/20");
  });
});
