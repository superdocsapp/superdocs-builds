import { describe, expect, it } from "vitest";

import {
  buildEditInstruction,
  createFilename,
  mapChangeToSections,
  renderSourceDocument,
  validateChange,
  verifyPreservedValues,
  verifyProposedChange
} from "./documentMapping.js";

const change = {
  id: "8f4d1b2c9a7e4d3f8b21c05e6a1d4471",
  number: "CHG0010042",
  short_description: "Upgrade production API gateway",
  configuration_item: "PROD-API-GATEWAY-01",
  work_notes:
    "Maintenance window completed. Traffic was drained before upgrade and restored after health checks passed.",
  resolution_code: "Successful",
  status: "Closed",
  requester: "Asha Rao",
  assignment_group: "Platform Engineering",
  risk: "Moderate",
  planned_start: "2026-08-18T22:00:00.000Z",
  planned_end: "2026-08-18T23:00:00.000Z"
};

describe("validation", () => {
  it("accepts a complete change", () => {
    expect(validateChange(change)).toEqual({ ok: true, missingFields: [] });
  });

  it("names every missing required field", () => {
    const result = validateChange({ ...change, work_notes: "", resolution_code: "   " });
    expect(result.ok).toBe(false);
    expect(result.missingFields).toEqual(["work_notes", "resolution_code"]);
  });
});

describe("mapping", () => {
  it("copies ServiceNow values into sections verbatim", () => {
    const sections = mapChangeToSections(change);
    const byTitle = Object.fromEntries(sections.map((section) => [section.title, section.content]));

    expect(byTitle["Configuration Item"]).toBe("PROD-API-GATEWAY-01");
    expect(byTitle["Work Notes"]).toBe(change.work_notes);
  });

  it("omits empty fields rather than writing placeholders", () => {
    const sections = mapChangeToSections({ ...change, risk: "" });
    expect(sections.some((section) => section.title === "Risk")).toBe(false);
  });

  it("uses the change number for the export filename", () => {
    expect(createFilename(change)).toBe("chg0010042-production-change-record.docx");
  });

  it("puts the preserved values in the instruction sent to SuperDocs", () => {
    const instruction = buildEditInstruction(change);
    expect(instruction).toContain("PROD-API-GATEWAY-01");
    expect(instruction).toContain(change.work_notes);
  });

  it("uploads the mapped record, not a summary of it", () => {
    const source = renderSourceDocument(change);
    expect(source).toContain("## Configuration Item\n\nPROD-API-GATEWAY-01");
    expect(source).toContain(change.work_notes);
  });
});

describe("per-change verification", () => {
  it("passes a rewrite that leaves ServiceNow values alone", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: "<h2>Change Summary</h2>",
      new_html: "<h2>Summary of Changes</h2>"
    });

    expect(result.verdict).toBe("safe");
    expect(result.recommendation).toBe("approve");
  });

  it("blocks a change that drops a preserved value", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: "<p>PROD-API-GATEWAY-01</p>",
      new_html: "<p>the production gateway</p>"
    });

    expect(result.verdict).toBe("blocked");
    expect(result.recommendation).toBe("reject");
    expect(result.findings[0].field).toBe("configuration_item");
  });

  it("blocks a new block that restates a preserved field with a different value", () => {
    // The real failure seen against the live API: a generated summary table
    // reworded the configuration item into its own house style.
    const result = verifyProposedChange(change, {
      operation: "create",
      old_html: null,
      new_html:
        "<h2>Executive Summary</h2><table><tr><td>Configuration Item</td><td>API-GW-PROD-01</td></tr></table>"
    });

    expect(result.verdict).toBe("blocked");
    expect(result.findings.some((finding) => finding.field === "configuration_item")).toBe(true);
  });

  it("flags but does not block a reworded resolution code", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: "<h2>Resolution</h2><p>Successful</p>",
      new_html: "<h2>Resolution</h2><p>The process was completed successfully.</p>"
    });

    expect(result.verdict).toBe("advisory");
    expect(result.recommendation).toBe("approve");
  });

  it("does not treat a field name used in prose as a restatement", () => {
    const result = verifyProposedChange(change, {
      operation: "create",
      old_html: null,
      new_html:
        "<p>Status was preserved via the traffic draining protocol, allowing for resolution without customer impact.</p>"
    });

    expect(result.findings).toEqual([]);
    expect(result.verdict).toBe("safe");
  });

  it("quotes where the values diverge instead of two identical-looking prefixes", () => {
    const result = verifyProposedChange(change, {
      operation: "create",
      old_html: null,
      new_html: `<p>Work Notes: Maintenance window completed. Traffic was drained before upgrade and restored once the team signed off.</p>`
    });

    const [finding] = result.findings.filter((entry) => entry.field === "work_notes");
    expect(finding).toBeDefined();
    expect(finding.reason).toContain("They match up to");
    expect(finding.reason).toContain("after health checks passed");
    expect(finding.reason).toContain("once the team signed off");
  });

  /**
   * Captured from a live run: asked for an Executive Summary, the model wrote
   * around the configuration item instead of quoting it. Nothing was removed
   * and nothing was restated under a label, so the first two rules stayed
   * silent and the change was rated safe.
   */
  it("flags added prose that discusses a preserved value without quoting it", () => {
    const result = verifyProposedChange(change, {
      operation: "create",
      old_html: null,
      new_html:
        "<h2>Executive Summary</h2><p>This production change record (CHG0010042) covers the upgrade of the production API gateway. The change involves the configuration item identified as the production API gateway to ensure the system is updated as per the change summary.</p>"
    });

    expect(result.verdict).toBe("advisory");
    expect(result.recommendation).toBe("approve");

    const [finding] = result.findings.filter((entry) => entry.field === "configuration_item");
    expect(finding.blocking).toBe(false);
    expect(finding.reason).toContain("PROD-API-GATEWAY-01");
  });

  /** The same model, one batch later, quoting the value. This must stay silent. */
  it("stays silent once the added prose quotes the value verbatim", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: "<p>The change involves the configuration item identified as the production API gateway.</p>",
      new_html:
        "<p>This production change record (CHG0010042) authorizes and documents the upgrade of the production API gateway (Configuration Item: PROD-API-GATEWAY-01). The objective is to keep the gateway secure and performant.</p>"
    });

    expect(result.verdict).toBe("safe");
  });

  /**
   * A heading is not a claim. Reading "Configuration Item" with nothing after
   * it as a restatement rated the chunk blocked, and the server refuses to
   * approve a blocked change — leaving a proposed heading the reviewer could
   * only ever reject.
   */
  it("does not flag a bare heading that names a preserved field", () => {
    const result = verifyProposedChange(change, {
      operation: "create",
      old_html: null,
      new_html: "<h2>Configuration Item</h2>"
    });

    expect(result.findings).toEqual([]);
    expect(result.verdict).toBe("safe");
  });

  it("still blocks a rewrite that empties out a preserved value", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: "<h2>Configuration Item</h2><p>PROD-API-GATEWAY-01</p>",
      new_html: "<h2>Configuration Item</h2>"
    });

    expect(result.verdict).toBe("blocked");
  });

  it("treats rewrapped whitespace as unchanged", () => {
    const result = verifyProposedChange(change, {
      operation: "edit",
      old_html: `<p>${change.work_notes}</p>`,
      new_html: `<p>Maintenance window completed.\n   Traffic was drained before upgrade\n   and restored after health checks passed.</p>`
    });

    expect(result.verdict).toBe("safe");
  });
});

describe("final document verification", () => {
  it("passes when both preserved values survive the edit", () => {
    const html = `<h1>Production Change Record</h1><p>${change.configuration_item}</p><p>${change.work_notes}</p>`;
    expect(verifyPreservedValues(change, html).ok).toBe(true);
  });

  it("fails when a preserved value is missing from the finished document", () => {
    const html = `<h1>Production Change Record</h1><p>API-GW-PROD-01</p><p>${change.work_notes}</p>`;
    const result = verifyPreservedValues(change, html);

    expect(result.ok).toBe(false);
    expect(result.checks.find((check) => check.field === "configuration_item")?.found).toBe(false);
  });
});
