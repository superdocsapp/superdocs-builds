// @vitest-environment jsdom

import { act, createElement, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: ReactNode; href: string } & Record<string, unknown>) => (
    createElement("a", { href, ...props }, children)
  ),
}));

vi.mock("../app/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../app/lib/api")>();
  return {
    ...actual,
    getConnections: vi.fn(),
    getRun: vi.fn(),
    listRuns: vi.fn(),
    listSources: vi.fn(),
    registerSource: vi.fn(),
    startRun: vi.fn(),
    resumeRun: vi.fn(),
    createDryRun: vi.fn(),
  };
});

import { AppShell } from "../app/components/app-shell";
import { Workspace } from "../app/components/workspace";
import {
  createDryRun,
  getConnections,
  getRun,
  listRuns,
  listSources,
  registerSource,
  startRun,
  type RunSummary,
  type RunView,
  type SourceRegistration,
} from "../app/lib/api";
import { documentConversationFromRuns } from "../app/lib/conversation";
import { TooltipProvider } from "../components/ui/tooltip";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const connection = {
  connection_id: "connection-1",
  provider: "GOOGLE" as const,
  status: "CONNECTED" as const,
  granted_scopes: [],
  last_validated_at: null,
  disconnected_at: null,
};

function source(captureId: string, revisionId: string): SourceRegistration {
  return {
    source: {
      source_id: "source-1",
      provider_file_id: "file-vendor",
      name: "Vendor Agreement",
      mime_type: "application/vnd.google-apps.document",
      parent_ids: ["folder-1"],
    },
    baseline: {
      capture_id: captureId,
      revision_id: revisionId,
      native_canonical_sha256: "a".repeat(64),
      docx_sha256: "b".repeat(64),
      docx_size_bytes: 512,
    },
    preview: {
      available: true,
      revision_id: revisionId,
      blocks: [{ kind: "paragraph", named_style: null, text: `Current Google revision ${revisionId}` }],
    },
  };
}

function run(overrides: Partial<RunSummary>): RunSummary {
  return {
    run_id: "run-a",
    watch_id: null,
    originating_scan_id: null,
    source_id: "source-1",
    provider_file_id: "file-vendor",
    document_name: "Vendor Agreement",
    instruction: "Change payment from 30 to 20.",
    proposal_count: 1,
    provider_version: null,
    source_revision_id: "R1",
    matched_rule_id: null,
    matched_rule_version: null,
    workflow_state: "SUCCEEDED",
    review_status: "REVIEWED",
    write_authorization_status: null,
    dry_run_status: "READY",
    write_back_status: "WRITE_VERIFIED",
    verification_status: "PASSED",
    last_error_code: null,
    conflict: null,
    ready_for_dry_run: false,
    ready_for_write_back: false,
    export: null,
    started_at: "2026-08-14T10:00:00Z",
    created_at: "2026-08-14T10:00:00Z",
    updated_at: "2026-08-14T10:05:00Z",
    finished_at: "2026-08-14T10:05:00Z",
    duration_ms: 300_000,
    external_effect_count: 2,
    external_effect_attempt_count: 2,
    external_effects_unknown: 0,
    superdocs_usage: {},
    ...overrides,
  };
}

const persistedRuns = [
  run({
    run_id: "run-b",
    instruction: "Now change support from 5 to 7.",
    source_revision_id: "R2",
    created_at: "2026-08-14T11:00:00Z",
    updated_at: "2026-08-14T11:05:00Z",
  }),
  run({ run_id: "run-a", updated_at: "2026-08-14T10:04:00Z" }),
  run({ run_id: "run-a" }),
  run({
    run_id: "other-document",
    provider_file_id: "file-other",
    document_name: "Other document",
  }),
];

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("persisted document conversation projection", () => {
  it("deduplicates by run id and orders turns by durable creation time", () => {
    const projected = documentConversationFromRuns(persistedRuns, "file-vendor");

    expect(projected.runs.map((item) => item.run_id)).toEqual(["run-a", "run-b"]);
    expect(projected.turns.map((turn) => turn.text)).toEqual([
      "Change payment from 30 to 20.",
      "Now change support from 5 to 7.",
    ]);
    expect(projected.turns.every((turn) => turn.persistedEvent?.kind === "verified")).toBe(true);
    expect(projected.activeRunId).toBeNull();
    expect(projected.canContinue).toBe(true);
  });

  it("keeps a real non-terminal run active and does not make historical review controls actionable", () => {
    const projected = documentConversationFromRuns([
      ...persistedRuns,
      run({
        run_id: "run-review",
        instruction: "Prepare the liability change.",
        workflow_state: "AWAITING_REVIEW",
        review_status: "AWAITING_DECISIONS",
        write_back_status: "AWAITING_REVIEW",
        verification_status: null,
        dry_run_status: "NOT_REQUESTED",
        proposal_count: 2,
        created_at: "2026-08-14T12:00:00Z",
        updated_at: "2026-08-14T12:02:00Z",
      }),
    ], "file-vendor");

    expect(projected.activeRunId).toBe("run-review");
    expect(projected.canContinue).toBe(false);
    expect(projected.turns.at(-1)?.persistedEvent).toBeUndefined();
    expect(projected.turns.slice(0, -1).every((turn) => turn.persistedEvent?.kind === "verified")).toBe(true);
  });

  it("continues only from terminal summaries that prove no write path was entered", () => {
    const safeStop = documentConversationFromRuns([
      run({
        workflow_state: "UNSUPPORTED",
        review_status: "FAILED",
        dry_run_status: "NOT_REQUESTED",
        write_back_status: "NOT_READY",
        verification_status: null,
        external_effects_unknown: 0,
      }),
    ], "file-vendor");
    const unknown = documentConversationFromRuns([
      run({
        workflow_state: "COMMIT_OUTCOME_UNKNOWN",
        write_back_status: "UNKNOWN",
        verification_status: null,
        external_effects_unknown: 1,
      }),
    ], "file-vendor");

    expect(safeStop.activeRunId).toBeNull();
    expect(safeStop.canContinue).toBe(true);
    expect(unknown.activeRunId).toBeNull();
    expect(unknown.canContinue).toBe(false);
  });
});

describe("recent document reopen", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
    vi.mocked(getConnections).mockReset();
    vi.mocked(getRun).mockReset();
    vi.mocked(listRuns).mockReset();
    vi.mocked(listSources).mockReset();
    vi.mocked(registerSource).mockReset();
    vi.mocked(startRun).mockReset();
    vi.mocked(createDryRun).mockReset();
    vi.mocked(getConnections).mockResolvedValue({
      oauth_configured: true,
      selected_scopes: [],
      connections: [connection],
    });
    vi.mocked(listRuns).mockResolvedValue({ runs: persistedRuns });
    vi.mocked(listSources).mockResolvedValue({ connection_id: "connection-1", sources: [] });
    vi.mocked(registerSource)
      .mockResolvedValueOnce(source("capture-R3", "R3"))
      .mockResolvedValueOnce(source("capture-R4", "R4"));
    vi.mocked(startRun).mockResolvedValue({
      run_id: "run-c",
      source_id: "source-1",
      provider_revision_id: "R4",
      state: "QUEUED",
      attention_code: null,
      session_id: null,
      session_document_id: null,
      durable_document_id: null,
      upload_version_id: null,
      final_version_id: null,
      provider_job_id: null,
      provider_job_status: null,
      awaiting_kind: null,
      pending_proposals: [],
      export: null,
      write_back: null,
    } satisfies RunView);
  });

  it("opens the existing read-only thread, shows the fresh source, and starts a new run for the next instruction", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(createElement(TooltipProvider, null,
        createElement(AppShell, null, createElement(Workspace)),
      ));
    });
    await flushEffects();

    const recentButton = Array.from(container.querySelectorAll("button")).find((button) => (
      button.textContent?.includes("Vendor Agreement")
    ));
    expect(recentButton).toBeTruthy();
    await act(async () => recentButton?.click());
    await flushEffects();

    expect(registerSource).toHaveBeenNthCalledWith(1, "connection-1", "file-vendor", expect.any(AbortSignal));
    // Shell load, the workspace's own history read, and the shell's refetch
    // once the document is open — that last one is what keeps Recent current
    // without a reload.
    expect(listRuns).toHaveBeenCalledTimes(3);
    expect(listSources).toHaveBeenCalledTimes(2);
    const text = container.textContent ?? "";
    expect(text.indexOf("Change payment from 30 to 20.")).toBeLessThan(text.indexOf("Now change support from 5 to 7."));
    expect(text.match(/Change written and verified\./g)).toHaveLength(2);
    expect(text).toContain("Current Google revision R3");
    expect(text).not.toContain("Approve");
    expect(text).not.toContain("Reject");
    expect(recentButton?.getAttribute("aria-current")).toBe("true");

    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(false);
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "Change renewal from 12 months to 6 months.");
      textarea.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        data: "Change renewal from 12 months to 6 months.",
        inputType: "insertText",
      }));
    });
    expect((container.querySelector('button[aria-label="Send instruction"]') as HTMLButtonElement).disabled).toBe(false);
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await flushEffects();

    expect(registerSource).toHaveBeenNthCalledWith(2, "connection-1", "file-vendor");
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith({
      source_id: "source-1",
      baseline_capture_id: "capture-R4",
      instruction: "Change renewal from 12 months to 6 months.",
    });

    root.unmount();
  });

  it("re-enables after a persisted mapping safe-stop and starts the next instruction from a fresh capture", async () => {
    const failedRunId = "run-mapping-safe-stop";
    vi.mocked(listRuns).mockResolvedValue({
      runs: [
        ...persistedRuns,
        run({
          run_id: failedRunId,
          instruction: "Replace the title.",
          workflow_state: "REVIEWED_EXPORT_READY",
          review_status: "REVIEWED",
          dry_run_status: "NOT_REQUESTED",
          write_back_status: "NOT_READY",
          verification_status: null,
          ready_for_dry_run: true,
          created_at: "2026-08-14T12:00:00Z",
          updated_at: "2026-08-14T12:05:00Z",
          finished_at: null,
        }),
      ],
    });
    vi.mocked(getRun).mockResolvedValue({
      run_id: failedRunId,
      source_id: "source-1",
      provider_revision_id: "R2",
      state: "REVIEWED_EXPORT_READY",
      attention_code: null,
      session_id: "session-1",
      session_document_id: "document-1",
      durable_document_id: null,
      upload_version_id: "upload-1",
      final_version_id: "final-1",
      provider_job_id: "job-1",
      provider_job_status: "completed",
      awaiting_kind: null,
      pending_proposals: [],
      export: null,
      write_back: null,
    });
    vi.mocked(createDryRun).mockResolvedValue({
      run_id: failedRunId,
      proposal_id: "proposal-1",
      status: "UNSUPPORTED",
      source: {
        provider: "GOOGLE",
        file_id: "file-vendor",
        baseline_revision_id: "R2",
        native_snapshot_sha256: "a".repeat(64),
      },
      old_text: null,
      new_text: null,
      context: null,
      changes: [],
      structural_location: null,
      operation_count: 0,
      operation_types: [],
      provider_operation: null,
      why_safe: [],
      mapping_proof_id: null,
      mapping_proof_sha256: null,
      write_plan_id: null,
      write_plan_sha256: null,
      reason_code: "MALFORMED_REVIEW_HTML",
      reason: "approved proposal cannot be safely mapped: proposal must contain one plain paragraph",
      candidate_count: null,
      cloud_mutation_performed: false,
    });

    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(createElement(TooltipProvider, null,
        createElement(AppShell, null, createElement(Workspace)),
      ));
    });
    await flushEffects();

    const recentButton = Array.from(container.querySelectorAll("button")).find((button) => (
      button.textContent?.includes("Vendor Agreement")
    ));
    await act(async () => recentButton?.click());
    await flushEffects();

    expect(getRun).toHaveBeenCalledWith(failedRunId, expect.any(AbortSignal));
    expect(createDryRun).toHaveBeenCalledWith(failedRunId);
    expect(container.textContent).toContain("No cloud changes were made.");
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    expect(textarea.disabled).toBe(false);

    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
      setter?.call(textarea, "Change payment from 30 days to 20 days.");
      textarea.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        data: "Change payment from 30 days to 20 days.",
        inputType: "insertText",
      }));
    });
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    });
    await flushEffects();

    expect(registerSource).toHaveBeenNthCalledWith(2, "connection-1", "file-vendor");
    expect(startRun).toHaveBeenCalledTimes(1);
    expect(startRun).toHaveBeenCalledWith({
      source_id: "source-1",
      baseline_capture_id: "capture-R4",
      instruction: "Change payment from 30 days to 20 days.",
    });

    root.unmount();
  });
});
