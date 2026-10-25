import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ============================================================
// Helpers
// ============================================================

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

// ============================================================
// Badge tests
// ============================================================

import { RegisterStatusBadge, TechnicalStatusBadge, FindingStatusBadge, ResultBadge } from "@/components/ui/Badge";

describe("RegisterStatusBadge", () => {
  it.each([
    ["NOT_RECEIVED", "Not Received"],
    ["RECEIVED", "Received"],
    ["UNDER_REVIEW", "Under Review"],
    ["REVIEWED", "Reviewed"],
    ["OVERDUE", "Overdue"],
  ])("renders label for status %s", (status, label) => {
    render(<RegisterStatusBadge status={status as any} />);
    expect(screen.getByText(label)).toBeTruthy();
  });

  it("renders visible text for screen reader access", () => {
    render(<RegisterStatusBadge status="OVERDUE" />);
    // Accessible text is the visible DOM text; CSS text-transform doesn't change it
    expect(screen.getByText("Overdue")).toBeTruthy();
  });
});

describe("TechnicalStatusBadge", () => {
  it("renders Deviation for REVIEWED_DEVIATION", () => {
    render(<TechnicalStatusBadge status="REVIEWED_DEVIATION" />);
    expect(screen.getByText("Deviation")).toBeTruthy();
  });

  it("renders Compliant for REVIEWED_COMPLIANT", () => {
    render(<TechnicalStatusBadge status="REVIEWED_COMPLIANT" />);
    expect(screen.getByText("Compliant")).toBeTruthy();
  });
});

describe("FindingStatusBadge", () => {
  it("renders Approved", () => {
    render(<FindingStatusBadge status="APPROVED" />);
    expect(screen.getByText("Approved")).toBeTruthy();
  });

  it("renders Clarification Requested", () => {
    render(<FindingStatusBadge status="CLARIFICATION_REQUESTED" />);
    expect(screen.getByText("Clarification Requested")).toBeTruthy();
  });
});

describe("ResultBadge", () => {
  it("renders Deviation for DEVIATION", () => {
    render(<ResultBadge result="DEVIATION" />);
    expect(screen.getByText("Deviation")).toBeTruthy();
  });

  it("renders Match for MATCH", () => {
    render(<ResultBadge result="MATCH" />);
    expect(screen.getByText("Match")).toBeTruthy();
  });
});

// ============================================================
// Button tests
// ============================================================

import { Button } from "@/components/ui/Button";

describe("Button", () => {
  it("renders children", () => {
    render(<Button>Click me</Button>);
    expect(screen.getByRole("button", { name: "Click me" })).toBeTruthy();
  });

  it("is disabled when loading", () => {
    render(<Button loading>Click me</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("disabled");
  });

  it("is disabled when disabled prop set", () => {
    render(<Button disabled>Click me</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("disabled");
  });

  it("calls onClick when clicked", async () => {
    const handler = vi.fn();
    render(<Button onClick={handler}>Click me</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not call onClick when disabled", async () => {
    const handler = vi.fn();
    render(<Button disabled onClick={handler}>Click me</Button>);
    await userEvent.click(screen.getByRole("button"));
    expect(handler).not.toHaveBeenCalled();
  });
});

// ============================================================
// ReviewProgress tests
// ============================================================

import { ReviewProgress } from "@/components/submittals/ReviewProgress";

describe("ReviewProgress", () => {
  it("shows Awaiting review when 0/n reviewed", () => {
    render(<ReviewProgress reviewed={0} total={3} />);
    expect(screen.getByText("Awaiting review")).toBeTruthy();
  });

  it("shows Review complete when all reviewed", () => {
    render(<ReviewProgress reviewed={3} total={3} />);
    expect(screen.getByText("Review complete")).toBeTruthy();
  });

  it("shows partial count", () => {
    render(<ReviewProgress reviewed={1} total={3} />);
    expect(screen.getByText("1 of 3 reviewed")).toBeTruthy();
  });

  it("shows correct percentage", () => {
    render(<ReviewProgress reviewed={2} total={4} />);
    expect(screen.getByText("50% complete")).toBeTruthy();
  });

  it("shows No findings when total is 0", () => {
    render(<ReviewProgress reviewed={0} total={0} />);
    expect(screen.getByText("No findings")).toBeTruthy();
  });

  it("progressbar has correct aria attributes", () => {
    render(<ReviewProgress reviewed={1} total={2} />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "50");
    expect(bar).toHaveAttribute("aria-valuemin", "0");
    expect(bar).toHaveAttribute("aria-valuemax", "100");
  });
});

// ============================================================
// Skeleton tests
// ============================================================

import { Skeleton, SkeletonCard } from "@/components/ui/Skeleton";

describe("Skeleton", () => {
  it("renders with animate-pulse class", () => {
    const { container } = render(<Skeleton />);
    expect(container.firstChild).toHaveClass("animate-pulse");
  });
});

describe("SkeletonCard", () => {
  it("renders without crashing", () => {
    const { container } = render(<SkeletonCard />);
    expect(container.firstChild).toBeTruthy();
  });
});

// ============================================================
// Utility function tests
// ============================================================

import {
  registerStatusLabel,
  technicalStatusLabel,
  findingStatusLabel,
  transmittalStatusLabel,
  formatDate,
  daysUntil,
  cn,
} from "@/lib/utils";

describe("registerStatusLabel", () => {
  it("maps NOT_RECEIVED", () => expect(registerStatusLabel("NOT_RECEIVED")).toBe("Not Received"));
  it("maps UNDER_REVIEW", () => expect(registerStatusLabel("UNDER_REVIEW")).toBe("Under Review"));
  it("maps OVERDUE", () => expect(registerStatusLabel("OVERDUE")).toBe("Overdue"));
});

describe("technicalStatusLabel", () => {
  it("maps REVIEWED_DEVIATION to Deviation", () =>
    expect(technicalStatusLabel("REVIEWED_DEVIATION")).toBe("Deviation"));
  it("maps REVIEWED_COMPLIANT to Compliant", () =>
    expect(technicalStatusLabel("REVIEWED_COMPLIANT")).toBe("Compliant"));
});

describe("findingStatusLabel", () => {
  it("maps PENDING_REVIEW", () =>
    expect(findingStatusLabel("PENDING_REVIEW")).toBe("Pending Review"));
  it("maps CLARIFICATION_REQUESTED", () =>
    expect(findingStatusLabel("CLARIFICATION_REQUESTED")).toBe("Clarification Requested"));
});

describe("transmittalStatusLabel", () => {
  it("maps EXPORTED to Exported", () =>
    expect(transmittalStatusLabel("EXPORTED")).toBe("Exported"));
  it("maps AWAITING_APPROVAL", () =>
    expect(transmittalStatusLabel("AWAITING_APPROVAL")).toBe("Awaiting Approval"));
});

describe("formatDate", () => {
  it("returns — for null", () => expect(formatDate(null)).toBe("—"));
  it("returns — for empty string", () => expect(formatDate("")).toBe("—"));
  it("formats a valid date string", () => {
    const result = formatDate("2026-08-19");
    expect(result).toMatch(/\d/); // has at least one digit
    expect(result).not.toBe("—");
  });
});

describe("daysUntil", () => {
  it("returns null for null", () => expect(daysUntil(null)).toBeNull());
  it("returns a number for a valid date", () => {
    const future = new Date();
    future.setDate(future.getDate() + 5);
    const result = daysUntil(future.toISOString().split("T")[0]);
    expect(typeof result).toBe("number");
  });
});

describe("cn", () => {
  it("merges class names", () => {
    expect(cn("a", "b")).toBe("a b");
  });
  it("handles conditional classes", () => {
    expect(cn("a", false && "b", "c")).toBe("a c");
  });
  it("deduplicates tailwind classes", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});
