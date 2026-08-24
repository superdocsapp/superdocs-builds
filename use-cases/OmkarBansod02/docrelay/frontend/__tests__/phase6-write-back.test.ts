// @vitest-environment jsdom

import { describe, expect, it, vi } from "vitest";
import fs from "fs";
import path from "path";
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";

import { DocumentWorkbench } from "../app/components/document-workbench";
import type { FrozenDocumentPreview, SourceRegistration } from "../app/lib/api";
import {
  recordVerifiedWrite,
  startRunRequest,
  type UserInstructionTurn,
} from "../app/lib/conversation";
import {
  canWriteBack,
  conflictActions,
  isVerifiedWriteSuccess,
} from "../app/lib/write-back-state";
import { TooltipProvider } from "../components/ui/tooltip";

function source(captureId = "capture-R1", revisionId = "R1"): SourceRegistration {
  return {
    source: {
      source_id: "source-1",
      provider_file_id: "file-1",
      name: "Vendor Agreement",
      mime_type: "application/vnd.google-apps.document",
      parent_ids: ["folder-1"],
    },
    baseline: {
      capture_id: captureId,
      revision_id: revisionId,
      native_canonical_sha256: "a".repeat(64),
      docx_sha256: "b".repeat(64),
      docx_size_bytes: 2048,
    },
    preview: {
      available: true,
      revision_id: revisionId,
      blocks: [{ kind: "paragraph", named_style: null, text: "Support requests are answered within 5 business days." }],
    },
  };
}

const verifiedPreview: FrozenDocumentPreview = {
  available: true,
  revision_id: "R2",
  blocks: [{ kind: "paragraph", named_style: null, text: "Support requests are answered within 7 business days." }],
};

describe("Phase 6 write-back state", () => {
  it("enables write only for a READY dry-run", () => {
    expect(canWriteBack("READY", false)).toBe(true);
    expect(canWriteBack("STALE", false)).toBe(false);
    expect(canWriteBack("READY", true)).toBe(false);
  });

  it("shows success only for verified backend success", () => {
    expect(isVerifiedWriteSuccess("WRITE_VERIFIED", true)).toBe(true);
    expect(isVerifiedWriteSuccess("WRITE_VERIFIED", false)).toBe(false);
    expect(isVerifiedWriteSuccess("IN_PROGRESS", true)).toBe(false);
  });

  it("offers only explicit cancel and review-latest conflict choices", () => {
    expect(conflictActions).toEqual([
      { choice: "CANCEL", label: "Cancel write-back" },
      { choice: "REVIEW_LATEST", label: "Review latest version" },
    ]);
    expect(JSON.stringify(conflictActions).toLowerCase()).not.toContain("overwrite");
  });

  it("guards the workspace write call with one in-flight claim", () => {
    const source = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/components/workspace.tsx"),
      "utf-8",
    );
    expect(source).toContain("writeInFlightRef.current");
    expect(source.match(/await writeBackSafely\(/g)).toHaveLength(1);
  });

  it("renders the conflict hero without an overwrite action", () => {
    const source = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/components/write-back-result.tsx"),
      "utf-8",
    );
    expect(source).toContain("Google Drive has a newer version");
    expect(source).toContain("Nothing was silently overwritten.");
    expect(source.toLowerCase()).not.toContain("overwrite anyway");
  });
});

describe("Phase 7 continuous document conversation", () => {
  it("keeps verified evidence, shows the verified postimage, and enables the composer", async () => {
    const turns: UserInstructionTurn[] = recordVerifiedWrite([
      {
        id: "turn-1",
        role: "user",
        text: "change 5 business days to 7",
        status: "accepted",
        runId: "run-A",
      },
    ], {
      runId: "run-A",
      fileId: "file-1",
      backupCreated: true,
      backupVerified: true,
      writeApplied: true,
      structurallyVerified: true,
    });
    const container = document.createElement("div");
    const root = createRoot(container);

    await act(async () => {
      root.render(createElement(TooltipProvider, null,
        createElement(DocumentWorkbench, {
          source: source(),
          turns,
          draft: "Now change payment from 30 days to 20 days",
          busy: false,
          composerEnabled: true,
          onDraftChange: vi.fn(),
          onSubmit: vi.fn(),
          onRetry: vi.fn(),
          onChangeSource: vi.fn(),
          documentPreview: verifiedPreview,
          documentRevision: "R2",
        }),
      ));
    });

    expect(container.textContent).toContain("Change written and verified.");
    expect(container.textContent).toContain("Support requests are answered within 7 business days.");
    expect(container.textContent).not.toContain("Support requests are answered within 5 business days.");
    expect(container.textContent).toContain("Revision R2");
    expect((container.querySelector("textarea") as HTMLTextAreaElement).disabled).toBe(false);
    root.unmount();
  });

  it("starts each instruction from the newly registered capture", () => {
    const newlyCaptured = source("capture-R3", "R3");
    expect(startRunRequest(newlyCaptured, "change payment to 20 days")).toEqual({
      source_id: "source-1",
      baseline_capture_id: "capture-R3",
      instruction: "change payment to 20 days",
    });

    const workspace = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/components/workspace.tsx"),
      "utf-8",
    );
    const recapture = workspace.indexOf("const runSource = await registerSource(");
    const start = workspace.indexOf("await startRun(startRunRequest(runSource, text))");
    expect(recapture).toBeGreaterThan(-1);
    expect(start).toBeGreaterThan(recapture);
  });
});
