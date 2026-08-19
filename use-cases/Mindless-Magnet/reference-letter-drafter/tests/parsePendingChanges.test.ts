import { describe, expect, it } from "vitest";
import { parsePendingChanges, pendingChangesFromJob, documentHtmlFromJob } from "@/lib/parsePendingChanges";
import type { JobStatusResponse } from "@/lib/types";

/**
 * These tests exist because of one line in the SuperDocs integration notes:
 * proposed-change content arrives as a JSON-encoded string, and missing the
 * second parse is the most common integration failure. The symptom is an
 * approve button over a blank diff, which is worse than an error, because a
 * reviewer will click it.
 *
 * The shapes below are the shapes the API has actually been observed to send,
 * plus the malformed ones a real integration has to survive.
 */

const change = {
  change_id: "c1",
  operation: "edit",
  chunk_id: "chunk-4",
  document_id: "doc-1",
  old_html: "<p>[placeholder]</p>",
  new_html: "<p>Dear Admissions Committee,</p>",
  ai_explanation: "Replaced the placeholder with the opening.",
};

describe("parsePendingChanges", () => {
  it("accepts a plain array", () => {
    const result = parsePendingChanges([change]);
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0].new_html).toBe("<p>Dear Admissions Committee,</p>");
    expect(result.problem).toBeUndefined();
  });

  it("accepts a JSON-encoded string, which is the documented wire shape", () => {
    const result = parsePendingChanges(JSON.stringify([change]));
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0].change_id).toBe("c1");
  });

  it("accepts a double-encoded string", () => {
    const result = parsePendingChanges(JSON.stringify(JSON.stringify([change])));
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0].ai_explanation).toBe("Replaced the placeholder with the opening.");
  });

  it("accepts the array nested under a key", () => {
    const result = parsePendingChanges({ pending_changes: JSON.stringify([change]) });
    expect(result.changes).toHaveLength(1);
  });

  it("accepts per-item encoded strings inside an array", () => {
    const result = parsePendingChanges([JSON.stringify(change)]);
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0].chunk_id).toBe("chunk-4");
  });

  it("returns nothing for empty inputs rather than a phantom change", () => {
    for (const input of [undefined, null, "", "[]", []]) {
      expect(parsePendingChanges(input).changes).toHaveLength(0);
    }
  });

  it("refuses a change with no id instead of rendering an unapprovable card", () => {
    const result = parsePendingChanges([{ new_html: "<p>text</p>" }]);
    expect(result.changes).toHaveLength(0);
    expect(result.problem).toMatch(/none can be safely reviewed/i);
  });

  it("refuses a change with an id but no content", () => {
    const result = parsePendingChanges([{ change_id: "c9" }]);
    expect(result.changes).toHaveLength(0);
    expect(result.problem).toBeDefined();
  });

  it("keeps the good changes and reports the malformed count", () => {
    const result = parsePendingChanges([change, { change_id: "c2" }]);
    expect(result.changes).toHaveLength(1);
    expect(result.problem).toMatch(/1 of 2/);
  });

  it("reports an unrecognised shape rather than silently showing zero changes", () => {
    const result = parsePendingChanges(42);
    expect(result.changes).toHaveLength(0);
    expect(result.problem).toMatch(/shape this app does not recognise/i);
  });

  it("does not loop forever on deeply nested strings", () => {
    let nested: string = JSON.stringify([change]);
    for (let i = 0; i < 12; i++) nested = JSON.stringify(nested);
    const result = parsePendingChanges(nested);
    // Beyond the unwrap depth it gives up honestly instead of hanging.
    expect(result.changes.length + (result.problem ? 1 : 0)).toBeGreaterThan(0);
  });

  it("normalises alternative field names from older payloads", () => {
    const result = parsePendingChanges([
      { id: "c3", before: "<p>a</p>", after: "<p>b</p>", explanation: "why" },
    ]);
    expect(result.changes[0]).toMatchObject({
      change_id: "c3",
      old_html: "<p>a</p>",
      new_html: "<p>b</p>",
      ai_explanation: "why",
      operation: "edit",
    });
  });

  it("coerces an unknown operation to edit rather than trusting it", () => {
    const result = parsePendingChanges([{ ...change, operation: "obliterate" }]);
    expect(result.changes[0].operation).toBe("edit");
  });
});

describe("pendingChangesFromJob", () => {
  const job = (metadata: Record<string, unknown>): JobStatusResponse => ({
    job_id: "j1",
    session_id: "s1",
    status: "awaiting_approval",
    metadata,
  });

  it("pulls changes out of job metadata", () => {
    expect(pendingChangesFromJob(job({ pending_changes: JSON.stringify([change]) })).changes).toHaveLength(1);
  });

  it("returns nothing when the job is asking whether to continue", () => {
    const result = pendingChangesFromJob(
      job({ awaiting_kind: "continue_prompt", pending_changes: JSON.stringify([change]) }),
    );
    expect(result.changes).toHaveLength(0);
  });

  it("handles a job with no metadata at all", () => {
    expect(pendingChangesFromJob(undefined).changes).toHaveLength(0);
  });
});

describe("documentHtmlFromJob", () => {
  it("reads the nested document_changes field", () => {
    const html = documentHtmlFromJob({
      job_id: "j",
      session_id: "s",
      status: "completed",
      result: { response: "done", document_changes: { updated_html: "<p>final</p>" } },
    });
    expect(html).toBe("<p>final</p>");
  });

  it("returns empty string when there is no document yet", () => {
    expect(documentHtmlFromJob({ job_id: "j", session_id: "s", status: "pending" })).toBe("");
  });
});
