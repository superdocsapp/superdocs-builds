import { describe, expect, it } from "vitest";
import { ApiError, type RegisteredSource, type RunSummary } from "../app/lib/api";
import {
  buildRegistrationPayload,
  extractSelectedFile,
  formatRelativeTime,
  importStageStatus,
  isDocRelayBackupName,
  mapImportFailure,
  mapPickerFailure,
  recentDocuments,
  recentDocumentsFromRuns,
} from "../app/lib/import-state";

function source(overrides: Partial<RegisteredSource> = {}): RegisteredSource {
  return {
    source_id: "source-1",
    provider_file_id: "file-1",
    name: "Vendor Agreement",
    mime_type: "application/vnd.google-apps.document",
    last_seen_at: "2026-08-12T09:00:00Z",
    ...overrides,
  };
}

function run(overrides: Partial<RunSummary>): RunSummary {
  return {
    run_id: "run-1",
    watch_id: null,
    originating_scan_id: null,
    source_id: "source-1",
    provider_file_id: "file-1",
    document_name: "Vendor Agreement",
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

describe("import stages", () => {
  it("marks file selected complete and reading active while register-source is in flight", () => {
    expect(importStageStatus("FILE_SELECTED", "READING_SOURCE")).toBe("complete");
    expect(importStageStatus("READING_SOURCE", "READING_SOURCE")).toBe("active");
    expect(importStageStatus("FREEZING_REVISION", "READING_SOURCE")).toBe("pending");
    expect(importStageStatus("PREPARING_WORKSPACE", "READING_SOURCE")).toBe("pending");
  });

  it("does not advance freeze or prepare independently of the register-source response", () => {
    expect(importStageStatus("FREEZING_REVISION", "READING_SOURCE")).not.toBe("active");
    expect(importStageStatus("PREPARING_WORKSPACE", "READING_SOURCE")).not.toBe("complete");
  });

  it("keeps later stages pending after a failed read", () => {
    expect(importStageStatus("FILE_SELECTED", "FAILED")).toBe("complete");
    expect(importStageStatus("READING_SOURCE", "FAILED")).toBe("pending");
    expect(importStageStatus("FREEZING_REVISION", "FAILED")).toBe("pending");
  });
});

describe("recent documents from real runs", () => {
  it("returns unique documents newest first and respects the limit", () => {
    const recent = recentDocumentsFromRuns([
      run({ run_id: "a", provider_file_id: "file-a", document_name: "A", updated_at: "2026-08-10T10:00:00Z" }),
      run({ run_id: "b", provider_file_id: "file-b", document_name: "B", updated_at: "2026-08-12T10:00:00Z" }),
      run({ run_id: "c", provider_file_id: "file-c", document_name: "C", updated_at: "2026-08-11T10:00:00Z" }),
      run({ run_id: "d", provider_file_id: "file-d", document_name: "D", updated_at: "2026-08-09T10:00:00Z" }),
    ], 3);

    expect(recent.map((item) => item.name)).toEqual(["B", "C", "A"]);
  });

  it("dedupes by provider file id and keeps the latest timestamp", () => {
    const recent = recentDocumentsFromRuns([
      run({ provider_file_id: "same", document_name: "Old", updated_at: "2026-08-01T00:00:00Z" }),
      run({ provider_file_id: "same", document_name: "New", updated_at: "2026-08-12T00:00:00Z" }),
    ]);

    expect(recent).toEqual([
      { providerFileId: "same", name: "New", updatedAt: "2026-08-12T00:00:00Z" },
    ]);
  });

  it("omits documents that lack a truthful name or file id", () => {
    expect(recentDocumentsFromRuns([
      run({ provider_file_id: "", document_name: "Missing file" }),
      run({ provider_file_id: "file-1", document_name: "   " }),
    ])).toEqual([]);
  });

  it("omits DocRelay backup artifacts from the user-facing recent list", () => {
    expect(isDocRelayBackupName("Vendor Agreement — DocRelay backup — 2026-08-14T12-00-00Z — A1roV34H9ERMvb0")).toBe(true);
    expect(isDocRelayBackupName("Vendor Agreement")).toBe(false);

    const recent = recentDocumentsFromRuns([
      run({ provider_file_id: "src", document_name: "Vendor Agreement", updated_at: "2026-08-14T12:00:00Z" }),
      run({
        run_id: "backup-run",
        provider_file_id: "backup-file",
        document_name: "Vendor Agreement — DocRelay backup — 2026-08-14T12-00-00Z — A1roV34H9ERMvb0",
        updated_at: "2026-08-14T12:01:00Z",
      }),
    ]);

    expect(recent.map((item) => item.providerFileId)).toEqual(["src"]);
    expect(recent[0]?.name).toBe("Vendor Agreement");
  });
});

describe("relative timestamps", () => {
  const now = Date.parse("2026-08-14T12:00:00Z");

  it("uses relative language for recent times", () => {
    expect(formatRelativeTime("2026-08-14T11:59:30Z", now)).toBe("Just now");
    expect(formatRelativeTime("2026-08-14T11:50:00Z", now)).toBe("10 minutes ago");
    expect(formatRelativeTime("2026-08-14T09:00:00Z", now)).toBe("3 hours ago");
    expect(formatRelativeTime("2026-08-13T12:00:00Z", now)).toBe("Yesterday");
  });
});

describe("import failure copy", () => {
  it("maps known provider codes without exposing HTTP status", () => {
    const failure = mapImportFailure(new ApiError(422, "UNSUPPORTED_SOURCE_TYPE", "Only native Google Docs are supported"));
    expect(failure.title).toBe("Only Google Docs are supported");
    expect(failure.protection).toContain("did not create or modify");
    expect(failure.title).not.toContain("422");
    expect(failure.protection).not.toContain("422");
  });

  it("uses a recoverable default for unknown failures", () => {
    const failure = mapImportFailure(new Error("network down"));
    expect(failure.title).toBe("Could not read this Google Doc");
    expect(failure.retryable).toBe(true);
  });
});

describe("picker failure copy", () => {
  it("treats popup close and access denied as a clean cancel", () => {
    expect(mapPickerFailure(new Error("popup_closed_by_user"))).toBeNull();
    expect(mapPickerFailure(new Error("OAuth popup was closed or denied"))).toBeNull();
    expect(mapPickerFailure(new Error("access_denied"))).toBeNull();
  });

  it("does not surface raw GIS or HTTP details", () => {
    const message = mapPickerFailure(new Error("idpiframe_initialization_failed"));
    expect(message).toBe("Google Drive could not be opened. Try again.");
    expect(message).not.toContain("idpiframe");
  });
});

describe("picker selection still does not register on cancel", () => {
  it("returns null for cancel and empty picks", () => {
    expect(extractSelectedFile({ action: "cancel" })).toBeNull();
    expect(extractSelectedFile({ action: "picked", docs: [] })).toBeNull();
  });

  it("registers only file_id after a valid pick", () => {
    const file = extractSelectedFile({
      action: "picked",
      docs: [{ id: "file-9", name: "Doc", mimeType: "application/vnd.google-apps.document" }],
    });
    expect(file).not.toBeNull();
    expect(buildRegistrationPayload(file!)).toEqual({ file_id: "file-9" });
  });
});

describe("recent documents from registered sources and the open document", () => {
  it("lists a registered source that has produced no run yet", () => {
    const recent = recentDocuments({ runs: [], sources: [source()] });

    expect(recent).toEqual([
      { providerFileId: "file-1", name: "Vendor Agreement", updatedAt: "2026-08-12T09:00:00Z" },
    ]);
  });

  it("collapses the same file reached through a source, a run and the open document", () => {
    const recent = recentDocuments({
      runs: [run({ provider_file_id: "file-1", document_name: "Vendor Agreement" })],
      sources: [source()],
      active: { providerFileId: "file-1", name: "Vendor Agreement" },
    });

    expect(recent).toHaveLength(1);
    // The run is newer than the last capture, so its timestamp wins.
    expect(recent[0]).toEqual({
      providerFileId: "file-1",
      name: "Vendor Agreement",
      updatedAt: "2026-08-12T12:00:00Z",
    });
  });

  it("shows the open document immediately and invents no timestamp for it", () => {
    const recent = recentDocuments({
      runs: [],
      sources: [],
      active: { providerFileId: "file-new", name: "Master Services Agreement" },
    });

    expect(recent).toEqual([
      { providerFileId: "file-new", name: "Master Services Agreement", updatedAt: "" },
    ]);
    expect(formatRelativeTime("")).toBe("");
  });

  it("pins the open document first without disturbing the rest of the order", () => {
    const recent = recentDocuments({
      runs: [
        run({ run_id: "b", provider_file_id: "file-b", document_name: "B", updated_at: "2026-08-13T10:00:00Z" }),
        run({ run_id: "c", provider_file_id: "file-c", document_name: "C", updated_at: "2026-08-11T10:00:00Z" }),
      ],
      sources: [source({ provider_file_id: "file-a", name: "A", last_seen_at: "2026-08-09T10:00:00Z" })],
      active: { providerFileId: "file-a", name: "A" },
    });

    expect(recent.map((item) => item.name)).toEqual(["A", "B", "C"]);
  });

  it("never lets a backup copy or a non-Google-Doc source enter Recent", () => {
    const recent = recentDocuments({
      sources: [
        source(),
        source({
          source_id: "source-2",
          provider_file_id: "file-backup",
          name: "Vendor Agreement — DocRelay backup — 2026-08-14T12-00-00Z — A1roV34H9ERMvb0",
          last_seen_at: "2026-08-14T12:05:00Z",
        }),
        source({
          source_id: "source-3",
          provider_file_id: "file-sheet",
          name: "Rate card",
          mime_type: "application/vnd.google-apps.spreadsheet",
          last_seen_at: "2026-08-14T13:00:00Z",
        }),
      ],
    });

    expect(recent.map((item) => item.providerFileId)).toEqual(["file-1"]);
  });
});
