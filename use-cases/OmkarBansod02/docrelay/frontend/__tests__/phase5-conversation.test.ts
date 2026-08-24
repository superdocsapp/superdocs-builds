// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ConversationComposer } from "../app/components/conversation-composer";
import {
  ConversationErrorEvent,
  ProcessingEvent,
  ReviewEvent,
} from "../app/components/conversation-events";
import { DocumentWorkbench } from "../app/components/document-workbench";
import { TooltipProvider } from "../components/ui/tooltip";
import type { GoogleConnection, ProposalView, RunView, SourceRegistration } from "../app/lib/api";
import {
  canSubmitComposer,
  composerEnterIntent,
  processingStepsFromRunState,
  workbenchStateLabel,
} from "../app/lib/conversation";

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
  };
}

function processingRun(overrides: Partial<RunView> = {}): RunView {
  return {
    run_id: "run-1",
    source_id: "source-1",
    provider_revision_id: "A1roV34H9ERMvb0Y",
    state: "EDITING",
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
    ...overrides,
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

function connection(): GoogleConnection {
  return {
    connection_id: "conn-1",
    provider: "GOOGLE",
    status: "CONNECTED",
    granted_scopes: [],
    last_validated_at: null,
    disconnected_at: null,
  };
}

describe("composer keyboard and busy send", () => {
  it("keeps Enter as send and Shift+Enter as newline", () => {
    expect(composerEnterIntent({ key: "Enter", shiftKey: false })).toBe("submit");
    expect(composerEnterIntent({ key: "Enter", shiftKey: true })).toBe("newline");
    expect(canSubmitComposer("Change payment terms", false)).toBe(true);
    expect(canSubmitComposer("Change payment terms", true)).toBe(false);
  });

  it("sends on Enter from the textarea and does not send on Shift+Enter", async () => {
    const onSubmit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ConversationComposer, {
          value: "Change payment terms from 30 days to 20 days.",
          busy: false,
          onChange: () => undefined,
          onSubmit,
        }),
      );
    });
    const textarea = container.querySelector("textarea") as HTMLTextAreaElement;
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }));
    });
    expect(onSubmit).not.toHaveBeenCalled();
    await act(async () => {
      textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: false, bubbles: true }));
    });
    expect(onSubmit).toHaveBeenCalledWith("Change payment terms from 30 days to 20 days.");
    root.unmount();
  });

  it("blocks duplicate send while busy and while the composer is not enabled", async () => {
    const onSubmit = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ConversationComposer, {
          value: "Change payment terms from 30 days to 20 days.",
          busy: true,
          enabled: true,
          onChange: () => undefined,
          onSubmit,
        }),
      );
    });
    const busyButton = container.querySelector("button[type='submit']") as HTMLButtonElement;
    expect(busyButton.disabled).toBe(true);
    await act(async () => busyButton.click());
    expect(onSubmit).not.toHaveBeenCalled();

    await act(async () => {
      root.render(
        createElement(ConversationComposer, {
          value: "Change payment terms from 30 days to 20 days.",
          busy: false,
          enabled: false,
          onChange: () => undefined,
          onSubmit,
        }),
      );
    });
    const disabledButton = container.querySelector("button[type='submit']") as HTMLButtonElement;
    expect(disabledButton.disabled).toBe(true);
    await act(async () => disabledButton.click());
    expect(onSubmit).not.toHaveBeenCalled();
    root.unmount();
  });
});

describe("processing stages map from real run state", () => {
  it("does not invent progress and follows QUEUED / BASELINING / EDITING", () => {
    expect(processingStepsFromRunState("QUEUED")).toEqual([
      { label: "Reading source", state: "current" },
      { label: "Preparing SuperDocs session", state: "idle" },
      { label: "Analyzing instruction", state: "idle" },
      { label: "Preparing proposals", state: "idle" },
    ]);
    expect(processingStepsFromRunState("BASELINING")).toEqual([
      { label: "Reading source", state: "complete" },
      { label: "Preparing SuperDocs session", state: "current" },
      { label: "Analyzing instruction", state: "idle" },
      { label: "Preparing proposals", state: "idle" },
    ]);
    expect(processingStepsFromRunState("EDITING")).toEqual([
      { label: "Reading source", state: "complete" },
      { label: "Preparing SuperDocs session", state: "complete" },
      { label: "Analyzing instruction", state: "current" },
      { label: "Preparing proposals", state: "idle" },
    ]);
  });

  it("renders the compact conversation processing event, not the old full-page wizard", () => {
    const html = renderToStaticMarkup(createElement(ProcessingEvent, { run: processingRun() }));
    expect(html).toContain("Preparing changes");
    expect(html).toContain("Reading source");
    expect(html).toContain("Analyzing instruction");
    expect(html).toContain("Preparing proposals");
    expect(html).not.toContain("Preparing your change");
    expect(html).not.toContain("mx-auto max-w-[760px]");
    expect(html).not.toContain("Waiting for review");
  });
});

describe("delayed status retry stays a safe read", () => {
  it("shows a conversational delay event and invokes the existing status handler", async () => {
    const onCheckStatus = vi.fn(async () => undefined);
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ProcessingEvent, {
          run: processingRun({
            attention_code: "SUPERDOCS_STATUS_READ_TIMEOUT",
            provider_read_error: {
              code: "SUPERDOCS_STATUS_READ_TIMEOUT",
              operation: "jobs.get",
              retryable: true,
              observed_at: "2026-08-14T16:24:00Z",
              occurrence_count: 1,
            },
          }),
          onCheckStatus,
        }),
      );
    });
    expect(container.textContent).toContain("Still checking the edit status.");
    expect(container.textContent).toContain("Your document has not been written.");
    expect(container.textContent).not.toContain("jobs.get");
    const button = Array.from(container.querySelectorAll("button")).find((candidate) =>
      candidate.textContent?.includes("Check status again"),
    );
    expect(button).toBeDefined();
    await act(async () => button?.click());
    expect(onCheckStatus).toHaveBeenCalledTimes(1);
    root.unmount();
  });
});

describe("review actions remain wired", () => {
  it("keeps approve, reject, and submit handlers on the conversation card", async () => {
    const onDecide = vi.fn();
    const onSubmitAll = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    const decisions = new Map<string, { approve: boolean }>([["proposal-1", { approve: true }]]);
    await act(async () => {
      root.render(
        createElement(ReviewEvent, {
          proposals: [proposal()],
          decisions,
          submitting: false,
          onDecide,
          onSubmitAll,
        }),
      );
    });
    const buttons = Array.from(container.querySelectorAll("button"));
    const approve = buttons.find((item) => item.textContent?.trim() === "Approved");
    const reject = buttons.find((item) => item.textContent?.trim() === "Reject");
    const submit = buttons.find((item) => item.textContent?.includes("Continue with 1 approved change"));
    await act(async () => approve?.click());
    await act(async () => reject?.click());
    await act(async () => submit?.click());
    expect(onDecide).toHaveBeenCalledWith("proposal-1", true);
    expect(onDecide).toHaveBeenCalledWith("proposal-1", false);
    expect(onSubmitAll).toHaveBeenCalledTimes(1);
    root.unmount();
  });
});

describe("workspace conversation uses ProcessingEvent only", () => {
  it("does not mount the old full-page processing component in Workspace", async () => {
    const fs = await import("fs");
    const path = await import("path");
    const sourceText = fs.readFileSync(
      path.resolve(import.meta.dirname, "../app/components/workspace.tsx"),
      "utf-8",
    );
    expect(sourceText).toContain("ProcessingEvent");
    expect(sourceText).not.toContain("ProcessingState");
    expect(sourceText).not.toContain("from \"./processing-state\"");
  });
});

describe("conversation empty state and pinned composer", () => {
  it("shows a real empty DocRelay turn and keeps the composer in the thread", () => {
    const html = renderToStaticMarkup(
      createElement(
        TooltipProvider,
        null,
        createElement(DocumentWorkbench, {
          source: source(),
          turns: [],
          draft: "",
          busy: false,
          composerEnabled: false,
          onDraftChange: () => undefined,
          onSubmit: () => undefined,
          onRetry: () => undefined,
          onChangeSource: () => undefined,
        }),
      ),
    );
    expect(html).toContain("Ready for an edit");
    expect(html).toContain("Ask for a targeted change to this document.");
    expect(html).toContain("Ask a question or request a change");
    expect(html).toContain("Press Enter to send");
    expect(html).toContain('aria-label="Send instruction"');
  });
});

describe("the empty state belongs to an empty thread only", () => {
  const workbench = (props: Record<string, unknown>) => renderToStaticMarkup(
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
        ...props,
      }),
    ),
  );

  it("shows the compact empty state with at most three examples", () => {
    const html = workbench({});
    expect(html).toContain("Ready for an edit");
    expect(html).toContain('aria-label="Example instructions"');
    expect(html.match(/<li class="min-w-0">/g) ?? []).toHaveLength(3);
  });

  it("disappears completely once the first instruction exists", () => {
    const html = workbench({
      turns: [{ id: "t1", role: "user", text: "Change 30 days to 45 days.", status: "accepted" }],
    });
    expect(html).not.toContain("Ready for an edit");
    expect(html).not.toContain('aria-label="Example instructions"');
    expect(html).toContain("Change 30 days to 45 days.");
  });

  it("disappears when a workflow event exists even with no instruction yet", () => {
    // The workspace always passes a list of conditional children; only the
    // rendered ones may count as conversation content.
    const html = workbench({
      children: [
        null,
        createElement(ConversationErrorEvent, {
          message: "Could not load this document's saved workflow history.",
          recoverable: true,
          onRetry: () => undefined,
        }),
        null,
      ],
    });
    expect(html).not.toContain("Ready for an edit");
    expect(html).toContain("saved workflow history");
  });

  it("still shows the empty state when every conditional child is null", () => {
    const html = workbench({ children: [null, null, null] });
    expect(html).toContain("Ready for an edit");
  });
});

describe("conversation header state labels stay truthful", () => {
  it("uses compact labels derived from workspace stage", () => {
    const conn = connection();
    const src = source();
    expect(workbenchStateLabel({ stage: "edit", connection: conn, source: src, submitting: false })).toBe("Active");
    expect(workbenchStateLabel({
      stage: "processing",
      connection: conn,
      source: src,
      run: processingRun(),
    })).toBe("Active");
    expect(workbenchStateLabel({
      stage: "review",
      connection: conn,
      source: src,
      run: processingRun({ state: "AWAITING_REVIEW" }),
      proposals: [proposal()],
      decisions: new Map(),
      submitting: false,
    })).toBe("Review");
    expect(workbenchStateLabel({
      stage: "error",
      connection: conn,
      source: src,
      run: processingRun({ state: "FAILED" }),
      message: "The edit run did not complete successfully.",
      recoverable: false,
    })).toBe("Needs attention");
  });
});

describe("recoverable errors stay conversational", () => {
  it("does not use a giant banner and keeps retry wired", async () => {
    const onRetry = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(ConversationErrorEvent, {
          message: "Dry run failed",
          recoverable: true,
          onRetry,
        }),
      );
    });
    expect(container.textContent).toContain("I couldn't finish this step.");
    expect(container.textContent).toContain("Your document has not been written.");
    expect(container.textContent).not.toContain("Something needs attention");
    const retry = Array.from(container.querySelectorAll("button")).find((item) =>
      item.textContent?.trim() === "Try again",
    );
    await act(async () => retry?.click());
    expect(onRetry).toHaveBeenCalledTimes(1);
    root.unmount();
  });
});
