// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { DocumentWorkbench } from "../app/components/document-workbench";
import { ConversationComposer } from "../app/components/conversation-composer";
import {
  ProcessingEvent,
  ReviewEvent,
} from "../app/components/conversation-events";
import { TooltipProvider } from "../components/ui/tooltip";
import { startRunRequest } from "../app/lib/conversation";
import type { ProposalView, RunView, SourceRegistration } from "../app/lib/api";

function source(): SourceRegistration {
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
        { kind: "paragraph", named_style: "NORMAL_TEXT", text: "Payment is due within 40 days." },
      ],
    },
  };
}

function processingRun(state: RunView["state"] = "EDITING"): RunView {
  return {
    run_id: "run-1",
    source_id: "source-1",
    provider_revision_id: "A1roV34H9ERMvb0Y",
    state,
    attention_code: null,
    provider_read_error: null,
    session_id: "session-1",
    session_document_id: "document-1",
    durable_document_id: null,
    upload_version_id: null,
    final_version_id: null,
    provider_job_id: "job-1",
    provider_job_status: "in_progress",
    awaiting_kind: null,
    pending_proposals: [],
    export: null,
    write_back: null,
  };
}

function proposal(): ProposalView {
  return {
    proposal_id: "proposal-1",
    review_round: 1,
    change_id: "change-1",
    operation: "replace",
    chunk_id: null,
    document_id: "document-1",
    old_html: "<p>Payment is due within 40 days.</p>",
    new_html: "<p>Payment is due within 25 days.</p>",
    ai_explanation: null,
    replaces_proposal_id: null,
    decision: null,
    feedback: null,
  };
}

describe("panels stay structurally distinct and contained", () => {
  it("renders a conversation region and a document region as separate labelled panels", () => {
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
    expect(html).toContain('aria-label="Document conversation"');
    expect(html).toContain('aria-label="Document"');
    // Desktop conversation geometry is one resizable, clamped width driven by
    // the `--conversation-w` custom property on the workbench.
    expect(html).toContain("conversation-pane");
    expect(html).toContain("--conversation-w:452px");
    expect(html).toContain('aria-label="Resize conversation pane"');
    expect(html).toContain('aria-valuemin="380"');
    expect(html).toContain('aria-valuemax="640"');
    // Document preview still uses the frozen source blocks.
    expect(html).toContain("Payment is due within 40 days.");
    expect(html).toContain("read-only");
  });
});

describe("processing renders the compact conversation variant", () => {
  it("shows conversation-native steps and not the old full-page processing screen", () => {
    const html = renderToStaticMarkup(
      createElement(ProcessingEvent, { run: processingRun() }),
    );
    expect(html).toContain("Preparing changes");
    expect(html).toContain("Reading source");
    expect(html).toContain("Preparing SuperDocs session");
    expect(html).toContain("Analyzing instruction");
    expect(html).toContain("Preparing proposals");
    // The old full-page ProcessingState heading must not appear in the conversation.
    expect(html).not.toContain("Preparing your change");
    expect(html).not.toContain("mx-auto max-w-[760px]");
  });
});

describe("review renders a contained conversation card, never the old page layout", () => {
  it("uses real proposal data and no fixed widths larger than the panel", () => {
    const html = renderToStaticMarkup(
      createElement(ReviewEvent, {
        proposals: [proposal()],
        decisions: new Map(),
        submitting: false,
        onDecide: () => undefined,
        onSubmitAll: () => undefined,
      }),
    );
    expect(html).toContain("1 change prepared for review");
    expect(html).toContain("Proposed change 1");
    expect(html).toContain(">40</mark>");
    expect(html).toContain(">25</mark>");
    expect(html).toContain("days.");
    expect(html).toContain("Reject");
    expect(html).toContain("Approve");
    // The old full-page ReviewPanel layout must never render inside the panel.
    expect(html).not.toContain("Review proposed changes");
    expect(html).not.toContain("Review evidence");
    expect(html).not.toContain("lg:grid-cols-[minmax(0,1fr)_270px]");
    expect(html).not.toContain("min-w-[160px]");
    expect(html).not.toContain("min-w-[180px]");
  });

  it("keeps approve/reject handlers functional", async () => {
    const onDecide = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ReviewEvent, {
          proposals: [proposal()],
          decisions: new Map(),
          submitting: false,
          onDecide,
          onSubmitAll: () => undefined,
        }),
      );
    });
    const buttons = Array.from(container.querySelectorAll("button"));
    const approve = buttons.find((b) => b.textContent?.trim() === "Approve");
    const reject = buttons.find((b) => b.textContent?.trim() === "Reject");
    await act(async () => approve?.click());
    await act(async () => reject?.click());
    expect(onDecide).toHaveBeenCalledWith("proposal-1", true);
    expect(onDecide).toHaveBeenCalledWith("proposal-1", false);
    root.unmount();
  });
});

describe("composer still sends the existing instruction unchanged", () => {
  it("submits the trimmed instruction and preserves the start-run request shape", async () => {
    const onSubmit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ConversationComposer, {
          value: "  Change payment terms from 40 days to 25 days.  ",
          busy: false,
          onChange: () => undefined,
          onSubmit,
        }),
      );
    });
    const form = container.querySelector("form") as HTMLFormElement;
    const button = container.querySelector("button[type='submit']") as HTMLButtonElement;
    expect(button.disabled).toBe(false);
    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });
    expect(onSubmit).toHaveBeenCalledWith("Change payment terms from 40 days to 25 days.");

    // Backend request shape is untouched.
    expect(startRunRequest(source(), "Change payment terms from 40 days to 25 days.")).toEqual({
      source_id: "source-1",
      baseline_capture_id: "capture-1",
      instruction: "Change payment terms from 40 days to 25 days.",
    });
    root.unmount();
  });
});
