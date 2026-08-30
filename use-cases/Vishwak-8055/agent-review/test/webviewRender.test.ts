import { describe, expect, it } from "vitest";
import {
  escapeHtml,
  renderChangeCard,
  renderDocument,
  renderWorkspaceBody,
  sanitizeFragment,
} from "../src/webviewRender";
import type { Change } from "../src/types";

function change(overrides: Partial<Change> = {}): Change {
  return {
    id: "c1",
    turnId: "s1:1",
    documentId: "doc1",
    chunkId: "a",
    operation: "edit",
    source: "auto_apply",
    sourceJobId: null,
    insertAfterChunkId: null,
    beforeHtml: '<p data-chunk-id="a">old</p>',
    afterHtml: '<p data-chunk-id="a">new</p>',
    status: "proposed",
    reconciliation: "match",
    aiExplanation: null,
    createdAt: "t0",
    updatedAt: "t0",
    decidedBy: null,
    decidedAt: null,
    ...overrides,
  };
}

describe("escapeHtml", () => {
  it("escapes the five dangerous characters", () => {
    expect(escapeHtml(`<script>alert('x')</script> & "quoted"`)).toBe(
      "&lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt; &amp; &quot;quoted&quot;"
    );
  });
});

describe("sanitizeFragment", () => {
  it("strips <script> tags entirely", () => {
    const out = sanitizeFragment('<p>hi</p><script>alert(1)</script><p>bye</p>');
    expect(out).not.toContain("<script");
    expect(out).not.toContain("alert(1)");
    expect(out).toContain("<p>hi</p>");
    expect(out).toContain("<p>bye</p>");
  });

  it("strips inline event handler attributes", () => {
    const out = sanitizeFragment(`<p onclick="alert(1)" data-chunk-id="a">click me</p>`);
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("alert(1)");
    expect(out).toContain("data-chunk-id");
  });

  it("neutralizes javascript: URLs", () => {
    const out = sanitizeFragment(`<a href="javascript:alert(1)">link</a>`);
    expect(out).not.toContain("javascript:");
  });

  it("strips iframes", () => {
    const out = sanitizeFragment(`<iframe src="https://evil.example"></iframe><p>ok</p>`);
    expect(out).not.toContain("<iframe");
    expect(out).toContain("<p>ok</p>");
  });

  it("leaves ordinary formatting markup untouched", () => {
    const html = '<h1 data-chunk-id="a">Title</h1><p><strong>bold</strong> and <em>italic</em></p>';
    expect(sanitizeFragment(html)).toBe(html);
  });

  it("strips SVG-based script vectors (onload, embedded <script>)", () => {
    const out = sanitizeFragment(`<svg onload="alert(1)"><script>alert(2)</script></svg><p>ok</p>`);
    expect(out).not.toContain("onload");
    expect(out).not.toContain("alert");
    expect(out).toContain("<p>ok</p>");
  });

  it("strips style attributes (a common CSS-based exfiltration/behavior vector)", () => {
    const out = sanitizeFragment(`<p style="background:url(javascript:alert(1))">text</p>`);
    expect(out).not.toContain("javascript:");
    expect(out).not.toContain("style=");
  });

  it("strips <form>/<input> so a fragment cannot present a fake credential prompt", () => {
    const out = sanitizeFragment(`<form action="https://evil.example"><input type="password"></form><p>ok</p>`);
    expect(out).not.toContain("<form");
    expect(out).not.toContain("<input");
    expect(out).toContain("<p>ok</p>");
  });

  it("preserves data-chunk-id and table layout attributes needed for correct rendering", () => {
    const html = '<table><tr><td data-chunk-id="c1" colspan="2">A</td></tr></table>';
    expect(sanitizeFragment(html)).toContain('data-chunk-id="c1"');
    expect(sanitizeFragment(html)).toContain('colspan="2"');
  });

  it("drops a link with a javascript: href entirely rather than passing a disarmed version through", () => {
    const out = sanitizeFragment(`<a href="javascript:alert(1)">click</a>`);
    expect(out).not.toContain("javascript:");
  });
});

describe("renderChangeCard", () => {
  it("renders Approve/Reject for a proposed change", () => {
    const html = renderChangeCard(change({ status: "proposed" }), 0);
    expect(html).toContain('data-action="approve"');
    expect(html).toContain('data-action="reject"');
    expect(html).not.toContain('data-action="revert"');
  });

  it("renders only Revert for an approved change", () => {
    const html = renderChangeCard(change({ status: "approved" }), 0);
    expect(html).toContain('data-action="revert"');
    expect(html).not.toContain('data-action="approve"');
  });

  it("renders conflict-resolution actions for a conflicted change", () => {
    const html = renderChangeCard(change({ status: "conflicted" }), 0);
    expect(html).toContain('data-action="resolve-approve"');
    expect(html).toContain('data-action="resolve-reject"');
  });

  it("renders no action buttons for a terminal rejected/reverted change", () => {
    expect(renderChangeCard(change({ status: "rejected" }), 0)).not.toContain("data-action");
    expect(renderChangeCard(change({ status: "reverted" }), 0)).not.toContain("data-action");
  });

  it("passes a malicious claim/explanation through escaping, not raw", () => {
    const html = renderChangeCard(
      change({ aiExplanation: `<img src=x onerror=alert(1)>` }),
      0
    );
    expect(html).not.toContain("<img src=x onerror");
    expect(html).toContain("&lt;img");
  });

  it("shows a placeholder rather than empty markup for a create (no beforeHtml)", () => {
    const html = renderChangeCard(change({ operation: "create", beforeHtml: null }), 0);
    expect(html).toContain("newly created");
  });
});

describe("renderWorkspaceBody", () => {
  it("shows the not-connected empty state when disconnected", () => {
    const body = renderWorkspaceBody({
      connected: false,
      changesByTurn: new Map(),
      turnRecords: new Map(),
      auditRecords: [],
    });
    expect(body).toContain("Not connected");
  });

  it("shows the connected-empty state when connected with no turns", () => {
    const body = renderWorkspaceBody({
      connected: true,
      changesByTurn: new Map(),
      turnRecords: new Map(),
      auditRecords: [],
    });
    expect(body).toContain("No agent turns observed yet");
  });

  it("renders turn sections when changes exist, most recent turn first", () => {
    const byTurn = new Map<string, Change[]>([
      ["s1:1", [change({ id: "c1", turnId: "s1:1" })]],
      ["s1:2", [change({ id: "c2", turnId: "s1:2" })]],
    ]);
    const body = renderWorkspaceBody({ connected: true, changesByTurn: byTurn, turnRecords: new Map(), auditRecords: [] });
    expect(body.indexOf("s1:2")).toBeLessThan(body.indexOf("s1:1"));
  });

  it("shows the instruction and the agent's reply as two distinct lines, not conflated", () => {
    const byTurn = new Map<string, Change[]>([["s1:1", [change({ id: "c1", turnId: "s1:1" })]]]);
    const turnRecords = new Map([
      [
        "s1:1",
        {
          turnId: "s1:1",
          sessionId: "s1",
          documentId: "doc1",
          clientType: "unknown",
          claimedIntentText: "Please update the version number.",
          claimedResultText: "I've updated the version number.",
          timestamp: "t",
        },
      ],
    ]);
    const body = renderWorkspaceBody({ connected: true, changesByTurn: byTurn, turnRecords, auditRecords: [] });
    expect(body).toContain("Please update the version number.");
    expect(body).toContain("I&#39;ve updated the version number."); // escapeHtml correctly escapes the apostrophe
    expect(body.indexOf("Instruction:")).toBeLessThan(body.indexOf("Agent reply:"));
  });
});

describe("renderDocument", () => {
  it("includes a strict CSP with no unsafe-inline and only the given nonce", () => {
    const html = renderDocument("<p>body</p>", "abc123", "vscode-webview://xyz");
    expect(html).toContain("Content-Security-Policy");
    expect(html).toContain("script-src 'nonce-abc123'");
    expect(html).not.toContain("unsafe-inline");
    expect(html).not.toContain("unsafe-eval");
  });
});
