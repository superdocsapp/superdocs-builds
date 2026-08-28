// @vitest-environment jsdom
import { describe, expect, it, beforeEach, vi } from "vitest";
import { act } from "react";

(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

const OLD_HTML =
  '<p data-chunk-id="74c123ae-7a80-44ec-a535-d216fcb42efd">We establish sharp spectral gap estimates, extending the classical Kesten bound <span data-latex="\\rho = \\frac{2\\sqrt{|S|-1}}{|S|}" data-type="inline-math">rho</span> to non-abelian settings.</p>';
const NEW_HTML =
  '<p data-chunk-id="74c123ae-7a80-44ec-a535-d216fcb42efd">We establish sharp spectral gap estimates, extending the classical Kesten bound <span data-latex="\\rho = \\frac{2\\sqrt{|S|-1}}{|S|}" data-type="inline-math">rho</span> to non-abelian settings, and we record the exact constant.</p>';

let posted: Record<string, unknown>[] = [];

function post(data: unknown): void {
  window.dispatchEvent(new MessageEvent("message", { data }));
}

async function mountApp(): Promise<void> {
  posted = [];
  (globalThis as Record<string, unknown>).acquireVsCodeApi = () => ({
    postMessage: (m: Record<string, unknown>) => posted.push(m),
    getState: () => undefined,
    setState: () => {},
  });
  vi.resetModules();
  await act(async () => {
    await import("../src/webview/app.tsx");
  });
}

async function authed(): Promise<void> {
  await act(async () => {
    post({ type: "authStatus", hasKey: true });
  });
}

function setComposer(text: string): void {
  const ta = document.querySelector(".composer textarea") as HTMLTextAreaElement;
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
  setter.call(ta, text);
  ta.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("webview app", () => {
  beforeEach(() => {
    document.body.innerHTML = '<div id="root"></div>';
  });

  it("renders the shell with composer and empty state", async () => {
    await mountApp();
    expect(document.querySelector("h1")?.textContent).toBe("LaTeX Bridge");
    expect(document.querySelector(".composer textarea")).toBeTruthy();
    await authed();
    expect(document.querySelector(".empty")).toBeTruthy();
  });

  it("shows the sign-in panel when no key is stored", async () => {
    await mountApp();
    await act(async () => {
      post({ type: "authStatus", hasKey: false });
    });
    expect(document.querySelector(".auth .signup")?.textContent).toContain("Create free account");
    expect(document.querySelector(".locked")).toBeTruthy();
  });

  it("shows quota and sign-out when authed", async () => {
    await mountApp();
    await act(async () => {
      post({
        type: "authStatus",
        hasKey: true,
        quota: { tier: "free", monthly_limit: 500, used: 3, remaining: 497 },
      });
    });
    expect(document.querySelector(".auth-head")?.textContent).toContain("SuperDocs");
    expect(document.querySelector(".quota")?.textContent).toContain("3/500 ops");
    expect(document.querySelector(".auth .ghost")?.textContent).toContain("Sign out");
  });

  it("signing in posts the key to the host", async () => {
    await mountApp();
    await act(async () => {
      post({ type: "authStatus", hasKey: false });
    });
    const input = document.querySelector(".auth input") as HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
    setter.call(input, "sk_test123");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await act(async () => {});
    (document.querySelector(".auth button:not(.signup)") as HTMLButtonElement).click();
    expect(posted.at(-1)).toEqual({ type: "setApiKey", key: "sk_test123" });
  });

  it("shows the workspace project badge", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({ type: "workspaceProject", path: "/home/user/math-paper" });
    });
    const badge = document.querySelector(".badge.project");
    expect(badge?.textContent).toContain("math-paper");
  });

  it("sends a chat message when a session exists", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({ type: "workspaceProject", path: "/home/user/math-paper" });
    });
    await act(async () => {
      post({ type: "sessionCreated", sessionId: "s1", chunksCount: 48, warnings: [], changes: [] });
    });
    setComposer("expand the abstract to two sentences");
    await act(async () => {});
    const sendBtn = Array.from(document.querySelectorAll(".composer-row button")).find(
      (b) => b.textContent?.trim() === "Send"
    ) as HTMLButtonElement;
    sendBtn.click();
    await act(async () => {});
    expect(posted.at(-1)).toEqual({ type: "requestEdit", message: "expand the abstract to two sentences" });
    const user = document.querySelector(".msg.user .msg-text");
    expect(user?.textContent).toContain("expand the abstract");
  });

  it("uploads the project first when no session exists yet", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({ type: "workspaceProject", path: "/home/user/math-paper" });
    });
    setComposer("add a lemma");
    await act(async () => {});
    const sendBtn = Array.from(document.querySelectorAll(".composer-row button")).find(
      (b) => b.textContent?.trim() === "Send"
    ) as HTMLButtonElement;
    sendBtn.click();
    expect(posted.at(-1)).toEqual({ type: "createSession", projectDir: "/home/user/math-paper" });
  });

  it("announces the session with ingest warnings", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({
        type: "sessionCreated",
        sessionId: "sess-123456789012345678901234",
        chunksCount: 48,
        warnings: [{ code: "TEX_PICTURE_PLACEHOLDER", message: "A vector drawing (TikZ/PSTricks) became a placeholder." }],
        changes: [],
      });
    });
    const badges = document.querySelectorAll(".badge");
    expect(Array.from(badges).some((b) => b.textContent?.includes("48 sections"))).toBe(true);
    expect(document.querySelector(".warnings .warning")?.textContent).toContain("TEX_PICTURE_PLACEHOLDER");
    const msg = document.querySelector(".msg.assistant .msg-text");
    expect(msg?.textContent).toContain("Project uploaded — 48 editable sections ready.");
  });

  it("renders review cards with old/new diff when awaiting approval, math preserved", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({
        type: "awaiting_approval",
        changes: [
          {
            change_id: "c1",
            operation: "edit",
            chunk_id: "74ef444a",
            old_html: OLD_HTML,
            new_html: NEW_HTML,
            ai_explanation: "Tighten the abstract and cite the bound.",
          },
        ],
      });
    });
    expect(document.querySelector(".badge.phase-awaiting")).toBeTruthy();
    const cards = document.querySelectorAll(".msg .review .card");
    expect(cards.length).toBe(1);
    const card = cards[0];
    expect(card.querySelector(".explain")?.textContent).toContain("Tighten the abstract");
    expect(card.querySelector(".diff-old")?.textContent).toContain("Kesten bound");
    expect(card.querySelector(".diff-new")?.innerHTML).toContain('data-latex="\\rho');
    expect(card.querySelector(".diff-new")?.textContent).toContain("exact constant");
  });

  it("accept/deny toggles and submit posts the decision subset", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({
        type: "awaiting_approval",
        changes: [
          { change_id: "c1", operation: "edit", chunk_id: "chunk-a", old_html: OLD_HTML, new_html: NEW_HTML },
          { change_id: "c2", operation: "insert", chunk_id: "chunk-b", old_html: "<p>old</p>", new_html: "<p>new</p>" },
        ],
      });
    });
    const cardButtons = document.querySelectorAll(".msg .review .card .decide button");
    const submit = document.querySelector(".msg .review .submit") as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    (cardButtons[0] as HTMLButtonElement).click();
    (cardButtons[3] as HTMLButtonElement).click();
    await act(async () => {});
    expect(submit.disabled).toBe(false);
    submit.click();
    expect(posted.at(-1)).toEqual({
      type: "submitDecisions",
      decisions: [
        { changeId: "c1", approved: true },
        { changeId: "c2", approved: false },
      ],
    });
  });

  it("shows the AI response after editCompleted", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({ type: "chat_started" });
    });
    await act(async () => {
      post({ type: "editCompleted", response: "Done — tightened the abstract.", changes: [] });
    });
    expect(document.querySelector(".response p")?.textContent).toContain("tightened the abstract");
  });

  it("shows export confirmation as an assistant message", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({
        type: "exportCompleted",
        saved: true,
        path: "/tmp/paper.docx",
        warnings: [{ code: "EQ_MATH", message: "Some math was simplified." }],
      });
    });
    const msg = document.querySelector(".msg.assistant .msg-text");
    expect(msg?.textContent).toContain("/tmp/paper.docx");
    expect(msg?.textContent).toContain("1 export warning");
  });

  it("shows errors inline in a message bubble", async () => {
    await mountApp();
    await authed();
    await act(async () => {
      post({ type: "error", message: "Instance at graph capacity" });
    });
    expect(document.querySelector(".badge.phase-error")).toBeTruthy();
    expect(document.querySelector(".msg .error-text")?.textContent).toContain("graph capacity");
  });
});
