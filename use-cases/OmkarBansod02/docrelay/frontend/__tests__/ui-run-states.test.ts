// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { contextRange, DiffView } from "../app/components/diff-view";
import { DryRunSummary } from "../app/components/dry-run-summary";
import { ProcessingState } from "../app/components/processing-state";
import { writeBackViewFromPersisted } from "../app/components/run-detail-workspace";
import { runStatusDisplay } from "../app/components/run-status";
import { WriteBackResult } from "../app/components/write-back-result";
import type { DryRunView, RunSummary, RunView, WriteBackView } from "../app/lib/api";

function run(overrides: Partial<RunSummary>): RunSummary {
  return {
    run_id: "run-1",
    watch_id: null,
    originating_scan_id: null,
    source_id: "source-1",
    provider_file_id: "file-1",
    document_name: "Document",
    instruction: "Change payment terms.",
    proposal_count: 1,
    provider_version: "5",
    source_revision_id: "rev-5",
    matched_rule_id: null,
    matched_rule_version: null,
    workflow_state: "AWAITING_REVIEW",
    review_status: "AWAITING_DECISIONS",
    write_authorization_status: null,
    dry_run_status: "NOT_REQUESTED",
    write_back_status: "AWAITING_REVIEW",
    verification_status: null,
    last_error_code: null,
    conflict: null,
    ready_for_dry_run: false,
    ready_for_write_back: false,
    export: null,
    started_at: null,
    created_at: "2026-08-12T11:59:00Z",
    updated_at: "2026-08-12T12:00:00Z",
    finished_at: null,
    duration_ms: null,
    external_effect_count: 0,
    external_effect_attempt_count: 0,
    external_effects_unknown: 0,
    superdocs_usage: {},
    ...overrides,
  };
}

describe("operational run state labels", () => {
  it("keeps authorization, conflict, unknown effect, and verified success distinct", () => {
    expect(runStatusDisplay(run({ write_back_status: "WRITE_AUTHORIZATION_REQUIRED" })).label).toBe("Write authorization required");
    expect(runStatusDisplay(run({ write_back_status: "CONFLICT" })).label).toBe("Conflict");
    expect(runStatusDisplay(run({ write_back_status: "UNKNOWN" })).label).toBe("External outcome unknown");
    expect(runStatusDisplay(run({ write_back_status: "WRITE_VERIFIED", verification_status: "PASSED" })).label).toBe("Verified");
  });
});

describe("contextual write preview", () => {
  it("highlights exact variable-length spans while preserving surrounding context", () => {
    const before = {
      text: "Payment is due within 45 days after receipt.",
      highlight_start: 22,
      highlight_end: 29,
    };
    const after = {
      text: "Payment is due within six business days after receipt.",
      highlight_start: 22,
      highlight_end: 39,
    };

    expect(contextRange(before.text, "45 days", before)).toEqual({ start: 22, end: 29 });
    expect(contextRange(after.text, "six business days", after)).toEqual({ start: 22, end: 39 });
    expect(before.text.slice(0, before.highlight_start)).toBe(
      after.text.slice(0, after.highlight_start),
    );
    expect(before.text.slice(before.highlight_end)).toBe(after.text.slice(after.highlight_end));

    const html = renderToStaticMarkup(
      createElement(DiffView, {
        oldText: "45 days",
        newText: "six business days",
        context: {
          offset_unit: "UNICODE_CODE_POINT",
          before,
          after,
          source_snapshot_id: "snapshot-1",
          native_snapshot_sha256: "a".repeat(64),
        },
      }),
    );
    expect(html).toContain(">45 days</mark>");
    expect(html).toContain(">six business days</mark>");
    expect(html).toContain("Context is read-only");
    expect(html).toContain(" after receipt.");
  });

  it("rejects a context span that does not contain the exact mutation text", () => {
    expect(
      contextRange("Payment is due within 45 days.", "30 days", {
        text: "Payment is due within 45 days.",
        highlight_start: 22,
        highlight_end: 29,
      }),
    ).toBeNull();
    expect(
      contextRange("📄 Payment 45", "45", {
        text: "📄 Payment 45",
        highlight_start: 10,
        highlight_end: 12,
      }),
    ).toEqual({ start: 10, end: 12 });
  });

  it("reuses matching frozen WritePlan context on verified success", () => {
    const html = renderToStaticMarkup(
      createElement(WriteBackResult, {
        document: { name: "Agreement", revision: "revision-1" },
        result: verifiedWrite({
          preview: {
            old_text: "0",
            new_text: "eight",
            context: {
              offset_unit: "UNICODE_CODE_POINT",
              before: {
                text: "Payment is due within 0 days after receipt.",
                highlight_start: 22,
                highlight_end: 23,
              },
              after: {
                text: "Payment is due within eight days after receipt.",
                highlight_start: 22,
                highlight_end: 27,
              },
              source_snapshot_id: "snapshot-1",
              native_snapshot_sha256: "a".repeat(64),
            },
          },
        }),
        deciding: false,
        onDecision: vi.fn(),
      }),
    );

    expect(html).toContain("What changed");
    expect(html).toContain("Payment is due within ");
    expect(html).toContain(">0</mark>");
    expect(html).toContain(">eight</mark>");
    expect(html).toContain(" days after receipt.");
    expect(html).toContain("Context is read-only");
  });

  it("lists every approved mapped change on dry-run and verified screens", () => {
    const payment = {
      offset_unit: "UNICODE_CODE_POINT" as const,
      before: {
        text: "Payment terms are 30 days.",
        highlight_start: 18,
        highlight_end: 20,
      },
      after: {
        text: "Payment terms are 14 days.",
        highlight_start: 18,
        highlight_end: 20,
      },
      source_snapshot_id: "snapshot-1",
      native_snapshot_sha256: "a".repeat(64),
    };
    const warranty = {
      offset_unit: "UNICODE_CODE_POINT" as const,
      before: {
        text: "Warranty lasts 12 months.",
        highlight_start: 15,
        highlight_end: 17,
      },
      after: {
        text: "Warranty lasts 24 months.",
        highlight_start: 15,
        highlight_end: 17,
      },
      source_snapshot_id: "snapshot-1",
      native_snapshot_sha256: "a".repeat(64),
    };
    const dryRunHtml = renderToStaticMarkup(
      createElement(DryRunSummary, {
        document: { name: "Agreement", revision: "revision-1" },
        dryRun: dryRun({
          old_text: "30",
          new_text: "14",
          context: payment,
          operation_count: 4,
          changes: [
            { proposal_id: "p1", old_text: "30", new_text: "14", context: payment, structural_location: {} },
            { proposal_id: "p2", old_text: "12", new_text: "24", context: warranty, structural_location: {} },
          ],
        }),
        writing: false,
        onWrite: () => undefined,
      }),
    );
    expect(dryRunHtml).toContain("2 approved changes will be written as 4 guarded Google Docs operations.");
    expect(dryRunHtml).toContain("Change 1");
    expect(dryRunHtml).toContain("Change 2");
    expect(dryRunHtml).toContain(">30</mark>");
    expect(dryRunHtml).toContain(">14</mark>");
    expect(dryRunHtml).toContain(">12</mark>");
    expect(dryRunHtml).toContain(">24</mark>");

    const verifiedHtml = renderToStaticMarkup(
      createElement(WriteBackResult, {
        document: { name: "Agreement", revision: "revision-1" },
        result: verifiedWrite({
          preview: {
            old_text: "30",
            new_text: "14",
            context: payment,
            changes: [
              { proposal_id: "p1", old_text: "30", new_text: "14", context: payment },
              { proposal_id: "p2", old_text: "12", new_text: "24", context: warranty },
            ],
          },
        }),
        deciding: false,
        onDecision: vi.fn(),
      }),
    );
    expect(verifiedHtml).toContain("Changes written and verified");
    expect(verifiedHtml).toContain("Change 1");
    expect(verifiedHtml).toContain("Change 2");
    expect(verifiedHtml).toContain(">30</mark>");
    expect(verifiedHtml).toContain(">24</mark>");
  });

  it("falls back to exact values when context is absent or belongs to another plan", () => {
    const olderRun = renderToStaticMarkup(
      createElement(WriteBackResult, {
        document: { name: "Agreement", revision: "revision-1" },
        dryRun: dryRun({ context: null }),
        result: verifiedWrite(),
        deciding: false,
        onDecision: vi.fn(),
      }),
    );
    expect(olderRun).toContain(">0</mark>");
    expect(olderRun).toContain(">8</mark>");
    expect(olderRun).not.toContain("Context is read-only");

    const mismatchedPlan = renderToStaticMarkup(
      createElement(WriteBackResult, {
        document: { name: "Agreement", revision: "revision-1" },
        change: { oldText: "0", newText: "8" },
        dryRun: dryRun({
          write_plan_id: "other-plan",
          context: {
            offset_unit: "UNICODE_CODE_POINT",
            before: { text: "Unrelated frozen context 0", highlight_start: 25, highlight_end: 26 },
            after: { text: "Unrelated frozen context 8", highlight_start: 25, highlight_end: 26 },
            source_snapshot_id: "snapshot-other",
            native_snapshot_sha256: "b".repeat(64),
          },
        }),
        result: verifiedWrite(),
        deciding: false,
        onDecision: vi.fn(),
      }),
    );
    expect(mismatchedPlan).not.toContain("Unrelated frozen context");
    expect(mismatchedPlan).toContain(">0</mark>");
    expect(mismatchedPlan).toContain(">8</mark>");
  });

  it("retains authoritative plan identity and preview on a persisted verified result", () => {
    const summary = run({
      workflow_state: "SUCCEEDED",
      dry_run_status: "READY",
      write_back_status: "WRITE_VERIFIED",
      verification_status: "PASSED",
      ready_for_dry_run: false,
      ready_for_write_back: false,
    });
    const verifiedRun = persistedRun({
      status: "WRITE_VERIFIED",
      write_plan_id: "plan-1",
      write_plan_sha256: "d".repeat(64),
      preview: {
        old_text: "0",
        new_text: "8",
        context: null,
      },
      backup_created: true,
      backup_verified: true,
      write_applied: true,
      structurally_verified: true,
      resulting_revision_id: "revision-2",
      conflict_detection_stage: null,
      conflict_decision: null,
    });

    expect(writeBackViewFromPersisted(verifiedRun, summary)).toMatchObject({
      write_plan_id: "plan-1",
      write_plan_sha256: "d".repeat(64),
      preview: { old_text: "0", new_text: "8", context: null },
    });
  });
});

function dryRun(overrides: Partial<DryRunView> = {}): DryRunView {
  return {
    run_id: "run-1",
    proposal_id: "proposal-1",
    status: "READY",
    source: {
      provider: "GOOGLE",
      file_id: "file-1",
      baseline_revision_id: "revision-1",
      native_snapshot_sha256: "a".repeat(64),
    },
    old_text: "0",
    new_text: "8",
    context: null,
    structural_location: {},
    operation_count: 1,
    operation_types: ["batchUpdate"],
    provider_operation: {},
    why_safe: [],
    mapping_proof_id: "proof-1",
    mapping_proof_sha256: "c".repeat(64),
    write_plan_id: "plan-1",
    write_plan_sha256: "d".repeat(64),
    reason_code: null,
    reason: null,
    candidate_count: 1,
    cloud_mutation_performed: false,
    ...overrides,
  };
}

function verifiedWrite(overrides: Partial<WriteBackView> = {}): WriteBackView {
  return {
    run_id: "run-1",
    status: "WRITE_VERIFIED",
    write_plan_id: "plan-1",
    write_plan_sha256: "d".repeat(64),
    backup_created: true,
    backup_verified: true,
    source_revision_verified: true,
    write_applied: true,
    structurally_verified: true,
    baseline_revision_id: "revision-1",
    resulting_revision_id: "revision-2",
    attention_code: null,
    conflict: null,
    ...overrides,
  };
}

function persistedRun(writeBack: RunView["write_back"]): RunView {
  return {
    run_id: "run-1",
    source_id: "source-1",
    provider_revision_id: "revision-1",
    state: writeBack?.status === "WRITE_VERIFIED" ? "SUCCEEDED" : "VERIFICATION_FAILED",
    attention_code: null,
    provider_read_error: null,
    session_id: "session-1",
    session_document_id: "document-1",
    durable_document_id: "durable-1",
    upload_version_id: "upload-1",
    final_version_id: "final-1",
    provider_job_id: "job-1",
    provider_job_status: "completed",
    awaiting_kind: null,
    pending_proposals: [],
    export: null,
    write_back: writeBack,
  };
}

describe("provider status timeout recovery", () => {
  it("shows a truthful read-only retry action and invokes it once", async () => {
    const onCheckStatus = vi.fn(async () => undefined);
    const container = document.createElement("div");
    const root = createRoot(container);
    const timedOutRun = {
      run_id: "run-1",
      source_id: "source-1",
      provider_revision_id: "revision-1",
      state: "EDITING",
      attention_code: "SUPERDOCS_STATUS_READ_TIMEOUT",
      provider_read_error: {
        code: "SUPERDOCS_STATUS_READ_TIMEOUT",
        operation: "jobs.get",
        retryable: true,
        observed_at: "2026-08-13T16:24:00Z",
        occurrence_count: 1,
      },
      session_id: "session-1",
      session_document_id: "document-1",
      durable_document_id: "durable-1",
      upload_version_id: "upload-1",
      final_version_id: null,
      provider_job_id: "job-1",
      provider_job_status: "in_progress",
      awaiting_kind: null,
      pending_proposals: [],
      export: null,
      write_back: null,
    } satisfies RunView;

    await act(async () => {
      root.render(
        createElement(ProcessingState, {
          document: { name: "Agreement", revision: "revision-1" },
          run: timedOutRun,
          onCheckStatus,
        }),
      );
    });

    expect(container.textContent).toContain("No cloud write was made.");
    expect(container.textContent).toContain("only reads jobs.get");
    const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
      candidate.textContent?.includes("Check status again"),
    );
    expect(button).toBeDefined();
    await act(async () => {
      button?.click();
    });
    expect(onCheckStatus).toHaveBeenCalledTimes(1);
    root.unmount();
  });
});
