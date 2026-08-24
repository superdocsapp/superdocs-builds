// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DocumentWorkbench } from "../app/components/document-workbench";
import { ConversationComposer } from "../app/components/conversation-composer";
import { DocumentPreviewUnavailable, DocumentRenderer } from "../app/components/document-renderer";
import { TooltipProvider } from "../components/ui/tooltip";
import type { SourceRegistration } from "../app/lib/api";
import {
  acceptInstruction,
  appendPendingInstruction,
  canSubmitComposer,
  composerEnterIntent,
  failInstruction,
  frozenPreviewBlocks,
  startRunRequest,
  workbenchSource,
} from "../app/lib/conversation";
import type { WorkspaceState } from "../app/lib/workspace-state";

function source(overrides: Partial<SourceRegistration> = {}): SourceRegistration {
  return {
    source: {
      source_id: "source-1",
      provider_file_id: "file-1",
      name: "Vendor Agreement",
      mime_type: "application/vnd.google-apps.document",
      parent_ids: ["folder-1"],
    },
    baseline: {
      capture_id: "capture-1",
      revision_id: "A1roV34H9ERMvb0Y",
      native_canonical_sha256: "a".repeat(64),
      docx_sha256: "b".repeat(64),
      docx_size_bytes: 2048,
    },
    preview: {
      available: true,
      revision_id: "A1roV34H9ERMvb0Y",
      blocks: [
        { kind: "heading", named_style: "HEADING_1", text: "Payment Terms" },
        { kind: "paragraph", named_style: "NORMAL_TEXT", text: "Payment terms are 30 days after receipt of a valid invoice." },
      ],
    },
    ...overrides,
  };
}

function connection(): WorkspaceState {
  return {
    stage: "edit",
    connection: {
      connection_id: "conn-1",
      provider: "GOOGLE",
      status: "CONNECTED",
      granted_scopes: [],
      last_validated_at: null,
      disconnected_at: null,
    },
    source: source(),
    submitting: false,
  };
}

describe("successful import opens the conversation/document workbench", () => {
  it("treats a registered source as workbench state with real title and revision", () => {
    const state = connection();
    expect(workbenchSource(state)?.source.name).toBe("Vendor Agreement");
    expect(workbenchSource(state)?.baseline.revision_id).toBe("A1roV34H9ERMvb0Y");

    const html = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(DocumentWorkbench, {
          source: source(),
          turns: [],
          draft: "",
          busy: false,
          composerEnabled: true,
          onDraftChange: () => undefined,
          onSubmit: () => undefined,
          onRetry: () => undefined,
          onChangeSource: () => undefined,
        }),
      ),
    );

    expect(html).toContain("Vendor Agreement");
    expect(html).toContain("A1roV3");
    expect(html).toContain("Ready for an edit");
    expect(html).toContain("Ask for a targeted change to this document.");
    expect(html).toContain("Ask a question or request a change");
    expect(html).toContain("Payment terms are 30 days after receipt of a valid invoice.");
    expect(html).not.toContain("What do you want to change?");
    expect(html).not.toContain("Start with a change");
  });
});

describe("frozen document rendering", () => {
  it("renders only persisted preview blocks", () => {
    const html = renderToStaticMarkup(
      createElement(DocumentRenderer, {
        title: "Vendor Agreement",
        blocks: source().preview!.blocks,
      }),
    );
    expect(html).toContain("Payment Terms");
    expect(html).toContain("30 days");
    expect(html).not.toContain("Confidentiality");
    expect(html).toContain("read-only");
  });

  it("never invents content when preview is unavailable", () => {
    expect(frozenPreviewBlocks({ available: false, revision_id: "rev", blocks: [] })).toBeNull();
    expect(frozenPreviewBlocks(undefined)).toBeNull();
    const html = renderToStaticMarkup(createElement(DocumentPreviewUnavailable));
    expect(html).toContain("Document preview isn&#x27;t available.");
    expect(html).toContain("frozen source");
    expect(html).not.toContain("30 days");
    expect(html).not.toContain("Payment Terms");
  });
});

describe("composer and existing instruction request", () => {
  it("sends the existing start-run request shape", () => {
    expect(startRunRequest(source(), "  Change payment terms from 30 days to 14 days.  ")).toEqual({
      source_id: "source-1",
      baseline_capture_id: "capture-1",
      instruction: "Change payment terms from 30 days to 14 days.",
    });
  });

  it("rejects an empty composer and a busy composer", () => {
    expect(canSubmitComposer("", false)).toBe(false);
    expect(canSubmitComposer("   ", false)).toBe(false);
    expect(canSubmitComposer("Change payment terms", true)).toBe(false);
    expect(canSubmitComposer("Change payment terms", false)).toBe(true);
  });

  it("uses Enter to submit and Shift+Enter for a newline", () => {
    expect(composerEnterIntent({ key: "Enter", shiftKey: false })).toBe("submit");
    expect(composerEnterIntent({ key: "Enter", shiftKey: true })).toBe("newline");
    expect(composerEnterIntent({ key: "a", shiftKey: false })).toBeNull();
  });

  it("disables send while busy so a second submit cannot start", async () => {
    const onSubmit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ConversationComposer, {
          value: "Change payment terms from 30 days to 14 days.",
          busy: true,
          onChange: () => undefined,
          onSubmit,
        }),
      );
    });
    const button = container.querySelector("button[type='submit']") as HTMLButtonElement;
    expect(button.disabled).toBe(true);
    await act(async () => {
      button.click();
    });
    expect(onSubmit).not.toHaveBeenCalled();
    root.unmount();
  });
});

describe("new document and post-submit handoff", () => {
  it("returns to the selector when source is cleared", () => {
    const afterNewDocument: WorkspaceState = {
      stage: "source",
      connection: connection().connection,
      loading: false,
    };
    expect(workbenchSource(afterNewDocument)).toBeNull();
  });

  it("keeps the accepted instruction while the existing run workflow continues", () => {
    const pending = appendPendingInstruction([], "Change payment terms from 30 days to 14 days.", "local-1");
    const accepted = acceptInstruction(pending, "local-1");
    expect(accepted[0]).toMatchObject({
      text: "Change payment terms from 30 days to 14 days.",
      status: "accepted",
    });
    const failed = failInstruction(pending, "local-1", "The instruction was not sent.");
    expect(failed[0].status).toBe("failed");
    expect(failed[0].error).toContain("not sent");
  });
});
