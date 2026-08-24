// @vitest-environment jsdom

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../app/lib/api", () => ({
  getAuthorizeUrl: () => "http://localhost:8000/api/v1/google/oauth/authorize",
  getConnections: vi.fn(async () => ({
    oauth_configured: true,
    selected_scopes: [],
    connections: [],
  })),
  listRuns: vi.fn(async () => ({ runs: [] })),
}));

import { listRuns } from "../app/lib/api";
import { SourceChooser } from "../app/components/source-chooser";
import {
  peekQueuedRecentDocument,
  requestOpenRecentDocument,
  takeQueuedRecentDocument,
} from "../app/lib/conversation";

async function flushEffects() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

describe("workspace starting surface", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("does not duplicate Recents on the workspace page", async () => {
    const container = document.createElement("div");
    const root = createRoot(container);

    await act(async () => {
      root.render(
        createElement(SourceChooser, {
          initialConnection: null,
          onDocumentPicked: () => undefined,
          onConnectionChange: () => undefined,
        }),
      );
    });
    await flushEffects();

    expect(container.textContent).toContain("Workspace");
    expect(container.textContent).toContain("Choose a Google Doc");
    expect(container.textContent).toContain("Start with a document");
    expect(container.textContent).toContain("Connect Google Drive");
    expect(container.textContent).toContain("Only Google Docs are supported.");
    expect(container.querySelector("svg")?.getAttribute("viewBox")).toBe("0 0 87.3 78");
    expect(container.textContent).not.toContain("Recent documents");
    expect(container.textContent).not.toContain("View all documents");
    expect(listRuns).not.toHaveBeenCalled();

    root.unmount();
  });
});

describe("recent document handoff", () => {
  it("queues a real document selection for the workspace", () => {
    takeQueuedRecentDocument();
    requestOpenRecentDocument({
      fileId: "file-vendor",
      name: "Vendor Agreement",
      mimeType: "application/vnd.google-apps.document",
    });
    expect(peekQueuedRecentDocument()).toEqual({
      fileId: "file-vendor",
      name: "Vendor Agreement",
      mimeType: "application/vnd.google-apps.document",
    });
    expect(takeQueuedRecentDocument()?.fileId).toBe("file-vendor");
    expect(peekQueuedRecentDocument()).toBeNull();
  });
});
