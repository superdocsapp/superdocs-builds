import { describe, expect, it } from "vitest";

import { awaitingKind, describeJob, nextAction } from "./workflow.js";

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

function newRun(overrides = {}) {
  return {
    sessionId: "svcflow-chg0010042-test",
    change,
    decisions: {},
    proposals: {},
    audit: [],
    ...overrides
  };
}

/** A finished document that still carries both preserved values. */
const goodHtml = `<h1>Production Change Record</h1><p>Configuration Item: ${change.configuration_item}</p><p>${change.work_notes}</p>`;

describe("awaitingKind", () => {
  /**
   * The bug this exists to prevent: a large edit pauses to ask whether to keep
   * going, reporting the same `awaiting_approval` status as a change batch. If
   * that is treated as a batch, the UI shows nothing to decide and the job
   * waits forever, because the approve endpoint cannot resolve it.
   */
  it("tells a continue prompt apart from a change batch", () => {
    expect(
      awaitingKind({ status: "awaiting_approval", metadata: { awaiting_kind: "continue_prompt" } })
    ).toBe("continue_prompt");

    expect(
      awaitingKind({
        status: "awaiting_approval",
        metadata: { pending_changes: [{ change_id: "c1", operation: "edit" }] }
      })
    ).toBe("change_batch");
  });

  it("treats an approval pause with no changes as a continue prompt", () => {
    expect(awaitingKind({ status: "awaiting_approval", metadata: {} })).toBe("continue_prompt");
  });

  it("is null when the job is not paused", () => {
    expect(awaitingKind({ status: "in_progress", metadata: {} })).toBeNull();
  });
});

describe("describeJob", () => {
  it("verifies every proposed change against the ServiceNow record", () => {
    const run = newRun();

    const state = describeJob(run, {
      status: "awaiting_approval",
      metadata: {
        pending_changes: [
          {
            change_id: "c1",
            operation: "edit",
            chunk_id: "chunk-1",
            ai_explanation: "Tidy the summary",
            old_html: `<p>${change.configuration_item}</p>`,
            new_html: "<p>API-GW-PROD-01</p>"
          }
        ]
      }
    });

    expect(state.proposedChanges[0].verification.verdict).toBe("blocked");
    expect(state.proposedChanges[0].chunkId).toBe("chunk-1");
    expect(state.proposedChanges[0].explanation).toBe("Tidy the summary");
    expect(state.awaitingApproval).toBe(true);
    expect(state.awaitingContinue).toBe(false);
  });

  it("remembers proposals server-side so a later decision is re-verified", () => {
    const run = newRun();

    describeJob(run, {
      status: "awaiting_approval",
      metadata: { pending_changes: [{ change_id: "c1", operation: "edit", new_html: "<p>x</p>" }] }
    });

    expect(run.proposals.c1.new_html).toBe("<p>x</p>");
  });

  it("does not report a failed job as successfully completed", () => {
    const run = newRun();
    const state = describeJob(run, { status: "failed", error: "model unavailable", metadata: {} });

    expect(state.finished).toBe(true);
    expect(state.failed).toBe(true);
    expect(run.completed).toBe(false);
    expect(state.readyToApprove).toBe(false);
    expect(state.nextAction.id).toBe("restart");
  });

  it("offers approval only once the document still matches ServiceNow", () => {
    const run = newRun();
    const state = describeJob(run, {
      status: "completed",
      metadata: {},
      result: { document_changes: { updated_html: goodHtml } }
    });

    expect(state.verification.ok).toBe(true);
    expect(state.readyToApprove).toBe(true);
    expect(state.exportReady).toBe(false);
    expect(state.nextAction.id).toBe("approve");
  });

  it("refuses to offer approval when a preserved value went missing", () => {
    const run = newRun();
    const state = describeJob(run, {
      status: "completed",
      metadata: {},
      result: { document_changes: { updated_html: "<p>API-GW-PROD-01</p>" } }
    });

    expect(state.verification.ok).toBe(false);
    expect(state.readyToApprove).toBe(false);
    expect(state.nextAction.id).toBe("blocked-final");
  });

  it("unlocks export only after a reviewer has signed off", () => {
    const run = newRun({ approved: true, approvedAt: "2026-08-23T07:00:00.000Z" });
    const state = describeJob(run, {
      status: "completed",
      metadata: {},
      result: { document_changes: { updated_html: goodHtml } }
    });

    expect(state.exportReady).toBe(true);
    expect(state.nextAction.id).toBe("export");
  });

  /**
   * Attribution lives server-side, so a reviewer who reloads the page still
   * sees who signed off rather than an approval with nobody's name on it.
   */
  it("carries the signatory and the checksum through", () => {
    const run = newRun({
      approved: true,
      approvedAt: "2026-08-23T07:00:00.000Z",
      reviewer: "A. Yendoti",
      checksum: "c2d46f88a0733c48"
    });

    const state = describeJob(run, {
      status: "completed",
      metadata: {},
      result: { document_changes: { updated_html: goodHtml } }
    });

    expect(state.reviewer).toBe("A. Yendoti");
    expect(state.checksum).toBe("c2d46f88a0733c48");
  });

  it("reports an unsigned run as unattributed rather than undefined", () => {
    const run = newRun();
    const state = describeJob(run, {
      status: "completed",
      metadata: {},
      result: { document_changes: { updated_html: goodHtml } }
    });

    expect(state.reviewer).toBeNull();
    expect(state.checksum).toBeNull();
  });

  it("carries the SuperDocs progress feed through", () => {
    const run = newRun();
    const state = describeJob(run, {
      status: "in_progress",
      progress: 42,
      metadata: {
        intermediate_responses: [
          { type: "user_facing", content: "Reading the document structure", sequence: 0 }
        ]
      }
    });

    expect(state.activity).toEqual([
      { sequence: 0, type: "user_facing", content: "Reading the document structure", at: null }
    ]);
    expect(state.nextAction.id).toBe("wait");
  });
});

describe("nextAction", () => {
  const base = { failed: false, awaitingContinue: false, finished: false, verification: null };

  it("puts a continue prompt ahead of everything else", () => {
    expect(nextAction({ ...base, awaitingContinue: true }, []).id).toBe("continue");
  });

  it("names blocked changes before ordinary ones", () => {
    const undecided = [
      { verification: { verdict: "safe" } },
      { verification: { verdict: "blocked" } },
      { verification: { verdict: "blocked" } }
    ];

    const action = nextAction(base, undecided);
    expect(action.id).toBe("reject-blocked");
    expect(action.label).toBe("Reject 2 blocked changes");
  });

  it("counts undecided changes in singular and plural", () => {
    expect(nextAction(base, [{ verification: { verdict: "safe" } }]).label).toBe(
      "Decide 1 proposed change"
    );
    expect(
      nextAction(base, [{ verification: { verdict: "safe" } }, { verification: { verdict: "safe" } }]).label
    ).toBe("Decide 2 proposed changes");
  });

  it("ends at done once the run is exported", () => {
    expect(
      nextAction({ ...base, finished: true, exported: true, verification: { ok: true, checks: [] } }, []).id
    ).toBe("done");
  });
});
