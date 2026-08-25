import { describe, expect, it } from "vitest";
import { cleanDetail, formatBytes, formatEvent, formatPeriod, formatTimestamp, statusLabel } from "./format";

describe("formatting helpers", () => {
  it("renders a period code as a readable month", () => {
    expect(formatPeriod("2026-03")).toBe("March 2026");
    expect(formatPeriod("")).toBe("");
  });

  it("returns an empty string rather than 'Invalid Date' for missing timestamps", () => {
    expect(formatTimestamp(null)).toBe("");
    expect(formatTimestamp("not-a-date")).toBe("");
  });

  it("formats a real timestamp", () => {
    expect(formatTimestamp("2026-08-16T10:42:00Z")).toMatch(/16 Aug 2026/);
  });

  it("labels audit events in plain language", () => {
    expect(formatEvent("SIGNOFF_APPROVED")).toBe("Sign-off approved");
    expect(formatEvent("SOMETHING_NEW")).toBe("Something new");
  });

  it("never shows a raw backend enum as a status", () => {
    expect(statusLabel("COMPLETE")).toBe("Complete");
    expect(statusLabel("REVIEW_REQUIRED")).toBe("Needs review");
    // An unmapped status must still read as a sentence, not as SCREAMING_SNAKE.
    expect(statusLabel("SOMETHING_ODD")).toBe("Something odd");
  });

  it("strips internal references out of audit details", () => {
    expect(cleanDetail("Pack generated (job 8f3a21c9-4d2e-11ee-be56)")).toBe("Pack generated");
    expect(cleanDetail("pack.zip (20212 bytes), memo a1b2c3d4e5f6")).toBe("pack.zip");
    expect(cleanDetail(null)).toBe("");
  });

  it("formats sizes", () => {
    expect(formatBytes(0)).toBe("0 KB");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
