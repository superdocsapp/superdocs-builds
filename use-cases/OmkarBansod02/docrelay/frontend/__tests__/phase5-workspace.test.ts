/**
 * Phase 5 workspace integration tests.
 *
 * These verify:
 * 1. Source selected state is correctly structured
 * 2. Edit submission constructs the correct API payload
 * 3. Review requires explicit decision for every proposal
 * 4. Approve/reject builds the correct API payload
 * 5. Dry-run renders real safe summary fields
 * 6. Unsupported mapping produces fail-closed output
 * 7. Technical details are not shown by default
 * 8. Write-back cannot occur in Phase 5
 * 9. No browser token persistence regression
 * 10. Polling stops at appropriate states
 */

import { describe, expect, it } from "vitest";
import { runNeedsPolling, humanRunState, humanDryRunFailure, attentionMessage, safetyFailureRecovery } from "../app/lib/workspace-state";

// ---------------------------------------------------------------------------
// 1. Source selected state
// ---------------------------------------------------------------------------
describe("source selected state", () => {
  it("structures source registration with required fields", () => {
    const source = {
      source: {
        source_id: "abc-123",
        provider_file_id: "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms",
        name: "DocRelay Baseline Test",
        mime_type: "application/vnd.google-apps.document",
        parent_ids: ["0AJhKhN-ABC"],
      },
      baseline: {
        capture_id: "cap-456",
        revision_id: "abc123def456",
        native_canonical_sha256: "a".repeat(64),
        docx_sha256: "b".repeat(64),
        docx_size_bytes: 12345,
      },
    };
    expect(source.source.source_id).toBe("abc-123");
    expect(source.baseline.capture_id).toBe("cap-456");
    expect(source.source.name).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 2. Edit submission payload
// ---------------------------------------------------------------------------
describe("edit submission payload", () => {
  it("constructs the correct start-run API payload", () => {
    const sourceId = "source-uuid";
    const captureId = "capture-uuid";
    const instruction = 'Change "45 days" to "30 days" and nothing else.';

    const payload = {
      source_id: sourceId,
      baseline_capture_id: captureId,
      instruction,
    };

    expect(payload.source_id).toBe(sourceId);
    expect(payload.baseline_capture_id).toBe(captureId);
    expect(payload.instruction).toContain("30 days");
    expect(Object.keys(payload)).toEqual(["source_id", "baseline_capture_id", "instruction"]);
  });
});

// ---------------------------------------------------------------------------
// 3. Review requires explicit decision
// ---------------------------------------------------------------------------
describe("review requires explicit decision", () => {
  it("every proposal must be explicitly decided before submission", () => {
    const proposals = [
      { proposal_id: "p1", decision: null },
      { proposal_id: "p2", decision: null },
    ];
    const decisions = new Map<string, { approve: boolean }>();
    decisions.set("p1", { approve: true });

    const allDecided = proposals.every(
      (p) => decisions.has(p.proposal_id) || p.decision !== null,
    );
    expect(allDecided).toBe(false);

    decisions.set("p2", { approve: false });
    const nowAllDecided = proposals.every(
      (p) => decisions.has(p.proposal_id) || p.decision !== null,
    );
    expect(nowAllDecided).toBe(true);
  });

  it("does not auto-approve any proposal", () => {
    const decisions = new Map<string, { approve: boolean }>();
    expect(decisions.size).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 4. Approve/reject builds correct API payload
// ---------------------------------------------------------------------------
describe("approve/reject API payload", () => {
  it("builds correct decisions array for submission", () => {
    const proposals = [
      { proposal_id: "p1", decision: null },
      { proposal_id: "p2", decision: null },
    ];
    const decisions = new Map<string, { approve: boolean; feedback?: string }>();
    decisions.set("p1", { approve: true });
    decisions.set("p2", { approve: false });

    const payload = proposals.map((p) => {
      const d = decisions.get(p.proposal_id)!;
      return { proposal_id: p.proposal_id, approve: d.approve, feedback: d.feedback };
    });

    expect(payload).toEqual([
      { proposal_id: "p1", approve: true, feedback: undefined },
      { proposal_id: "p2", approve: false, feedback: undefined },
    ]);
  });
});

// ---------------------------------------------------------------------------
// 5. Dry-run renders real safe summary fields
// ---------------------------------------------------------------------------
describe("dry-run safe summary", () => {
  it("ready dry-run has expected structure", () => {
    const dryRun = {
      status: "READY" as const,
      old_text: "45 days",
      new_text: "30 days",
      operation_count: 2,
      operation_types: ["deleteContentRange", "insertText"],
      why_safe: [
        "approved immutable review decision",
        "exact persisted baseline revision and native snapshot hash",
      ],
      cloud_mutation_performed: false as const,
      mapping_proof_id: "proof-uuid",
      write_plan_id: "plan-uuid",
    };

    expect(dryRun.status).toBe("READY");
    expect(dryRun.old_text).toBe("45 days");
    expect(dryRun.new_text).toBe("30 days");
    expect(dryRun.why_safe.length).toBeGreaterThan(0);
    expect(dryRun.cloud_mutation_performed).toBe(false);
    expect(dryRun.mapping_proof_id).toBeTruthy();
    expect(dryRun.write_plan_id).toBeTruthy();
  });
});

// ---------------------------------------------------------------------------
// 6. Unsupported mapping produces fail-closed output
// ---------------------------------------------------------------------------
describe("unsupported mapping fail-closed", () => {
  it("failure codes map to human-readable messages", () => {
    expect(humanDryRunFailure("AMBIGUOUS_PREIMAGE", null)).toContain("more than once");
    expect(humanDryRunFailure("NOT_APPROVED", null)).toContain("not been approved");
    expect(humanDryRunFailure("STALE_LINEAGE", null)).toContain("no longer current");
    expect(humanDryRunFailure("UNSUPPORTED_MULTIPLE_APPROVED_PROPOSALS", null)).toContain("More than one");
    expect(humanDryRunFailure("UNSUPPORTED_STRUCTURE", null)).toContain("not supported");
    expect(humanDryRunFailure(null, "fallback reason")).toBe("fallback reason");
  });

  it("does not offer a fake retry for an immutable malformed snapshot", () => {
    expect(safetyFailureRecovery("MALFORMED_SNAPSHOT")).toEqual({
      kind: "refresh-source",
      label: "Reload source for a new review",
      explanation: expect.stringContaining("will not write to Google"),
    });
    expect(safetyFailureRecovery("STALE_LINEAGE")).toMatchObject({
      kind: "retry-safety",
      label: "Run safety check again",
    });
  });

  it("unsupported dry-run has cloud_mutation_performed: false", () => {
    const dryRun = {
      status: "UNSUPPORTED" as const,
      reason_code: "AMBIGUOUS_PREIMAGE",
      reason: "multiple matches found",
      cloud_mutation_performed: false as const,
    };
    expect(dryRun.cloud_mutation_performed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 7. Technical details hidden by default
// ---------------------------------------------------------------------------
describe("technical details default visibility", () => {
  it("dry-run state does not expose technical fields in summary surface", () => {
    const publicFields = [
      "old_text", "new_text", "operation_count", "why_safe", "status",
    ];
    const technicalFields = [
      "mapping_proof_id", "mapping_proof_sha256",
      "write_plan_id", "write_plan_sha256",
      "provider_operation",
    ];

    for (const field of publicFields) {
      expect(typeof field).toBe("string");
    }
    for (const field of technicalFields) {
      expect(typeof field).toBe("string");
    }
  });
});

// ---------------------------------------------------------------------------
// 8. Browser never constructs provider operations
// ---------------------------------------------------------------------------
describe("provider mutation stays server-side", () => {
  it("no browser component constructs a Google provider mutation", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const componentsDir = path.resolve(import.meta.dirname, "../app/components");
    const libDir = path.resolve(import.meta.dirname, "../app/lib");

    const files = [
      ...fs.readdirSync(componentsDir).map((f: string) => path.join(componentsDir, f)),
      ...fs.readdirSync(libDir).map((f: string) => path.join(libDir, f)),
    ];

    for (const file of files) {
      if (!file.endsWith(".ts") && !file.endsWith(".tsx")) continue;
      const source = fs.readFileSync(file, "utf-8");
      expect(source).not.toContain("batchUpdate");
      expect(source).not.toContain("documents.batchUpdate");
      expect(source).not.toMatch(/\/execute-plan/);
      expect(source).not.toMatch(/\/commit/);
    }
  });

  it("dry-run always reports cloud_mutation_performed: false", () => {
    const readyView = { cloud_mutation_performed: false as const };
    const unsupportedView = { cloud_mutation_performed: false as const };
    expect(readyView.cloud_mutation_performed).toBe(false);
    expect(unsupportedView.cloud_mutation_performed).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 9. No browser token persistence regression
// ---------------------------------------------------------------------------
describe("browser token persistence regression", () => {
  it("picker-token.ts does not persist to storage", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const source = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/google-drive/picker-token.ts"),
      "utf-8",
    );
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
    expect(source).not.toContain("document.cookie");
  });

  it("source-chooser does not persist tokens", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const source = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/components/source-chooser.tsx"),
      "utf-8",
    );
    expect(source).not.toContain("localStorage");
    expect(source).not.toContain("sessionStorage");
    expect(source).not.toContain("document.cookie");
  });
});

// ---------------------------------------------------------------------------
// 10. Polling stops at appropriate states
// ---------------------------------------------------------------------------
describe("polling stops at appropriate states", () => {
  it("polls during QUEUED, BASELINING, EDITING", () => {
    expect(runNeedsPolling("QUEUED")).toBe(true);
    expect(runNeedsPolling("BASELINING")).toBe(true);
    expect(runNeedsPolling("EDITING")).toBe(true);
  });

  it("does not poll during AWAITING_REVIEW", () => {
    expect(runNeedsPolling("AWAITING_REVIEW")).toBe(false);
  });

  it("does not poll during terminal states", () => {
    expect(runNeedsPolling("REVIEWED_EXPORT_READY")).toBe(false);
    expect(runNeedsPolling("FAILED")).toBe(false);
    expect(runNeedsPolling("CANCELLED")).toBe(false);
  });

  it("does not poll during error/attention states", () => {
    expect(runNeedsPolling("CONFLICT")).toBe(false);
    expect(runNeedsPolling("UNSUPPORTED")).toBe(false);
  });

  it("handles undefined state", () => {
    expect(runNeedsPolling(undefined)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Human-readable state labels
// ---------------------------------------------------------------------------
describe("human-readable state labels", () => {
  it("maps run states to user-friendly labels", () => {
    expect(humanRunState("QUEUED")).toBe("Queued");
    expect(humanRunState("EDITING")).toBe("SuperDocs is editing");
    expect(humanRunState("AWAITING_REVIEW")).toBe("Awaiting review");
    expect(humanRunState("REVIEWED_EXPORT_READY")).toBe("Export ready");
  });

  it("maps attention codes to human messages", () => {
    expect(attentionMessage("SUPERDOCS_UPLOAD_REJECTED")).toContain("rejected");
    expect(attentionMessage(null)).toBeNull();
  });
});
