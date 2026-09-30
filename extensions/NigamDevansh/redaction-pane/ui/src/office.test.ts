import { describe, expect, it } from "vitest";
import { FakeHost, type Redaction } from "./office";

const item = (text: string, part: Redaction["part"], marker: string): Redaction => ({
  text,
  part,
  marker,
});

describe("what redaction does per part", () => {
  it("uses each item's own marker, not one for the batch", () => {
    // A card and a name in one call must not both become the same string.
    const host = new FakeHost("card 4111 1111 1111 1111 held for Harold Vance");

    void host.redact([
      item("4111 1111 1111 1111", "body", "[CREDIT CARD REDACTED]"),
      item("Harold Vance", "body", "[NAME REDACTED]"),
    ]);

    expect(host.text).toBe("card [CREDIT CARD REDACTED] held for [NAME REDACTED]");
  });

  it("refuses a tracked deletion instead of reporting it removed", async () => {
    // Word's `search` does not match struck-through runs, so there is no range
    // to replace. Reporting success here would put "redacted" in the log for an
    // SSN still sitting in the file.
    const host = new FakeHost("Previous contact: Harold Vance");

    const result = await host.redact([item("Harold Vance", "tracked_del", "[NAME REDACTED]")]);

    expect(result.applied).toBe(0);
    expect(result.failed[0].reason).toContain("tracked deletion");
    expect(host.text).toContain("Harold Vance");
  });

  it("reports a string it could not find rather than swallowing it", async () => {
    const host = new FakeHost("nothing sensitive here");

    const result = await host.redact([item("Harold Vance", "body", "[NAME REDACTED]")]);

    expect(result.applied).toBe(0);
    expect(result.failed).toHaveLength(1);
  });
});
