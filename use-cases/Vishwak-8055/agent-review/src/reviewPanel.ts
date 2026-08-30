import * as vscode from "vscode";
import type { ReviewStore } from "./reviewStore";
import type { Change, TurnRecord } from "./types";
import { renderDocument, renderWorkspaceBody } from "./webviewRender";

type IncomingAction = "approve" | "reject" | "revert" | "resolve-approve" | "resolve-reject";
const VALID_ACTIONS: readonly IncomingAction[] = ["approve", "reject", "revert", "resolve-approve", "resolve-reject"];

interface IncomingMessage {
  type: "action";
  action: IncomingAction;
  changeId: string;
}

/**
 * Never trust webview input — validate shape before acting on it, per the
 * brief's webview-security requirements. A malformed message (wrong shape,
 * unknown action) is silently dropped rather than executed.
 */
function isValidIncomingMessage(msg: unknown): msg is IncomingMessage {
  if (typeof msg !== "object" || msg === null) return false;
  const m = msg as Record<string, unknown>;
  return (
    m.type === "action" &&
    typeof m.changeId === "string" &&
    m.changeId.length > 0 &&
    typeof m.action === "string" &&
    (VALID_ACTIONS as readonly string[]).includes(m.action)
  );
}

function generateNonce(): string {
  let text = "";
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  for (let i = 0; i < 32; i++) text += chars.charAt(Math.floor(Math.random() * chars.length));
  return text;
}

export class ReviewPanel {
  static readonly viewType = "superdocsAgentReview.panel";

  private panel: vscode.WebviewPanel | undefined;
  private connected = false;
  private disposed = false;

  constructor(
    private readonly store: ReviewStore,
    /**
     * Fetches current live chunk content for a document — needed to
     * content-safety-check a reject/revert before applying it. Injected
     * rather than this class holding a SuperDocsClient directly, so the
     * panel has no network dependency of its own: it only ever talks to
     * the store and to VS Code's webview API.
     */
    private readonly getLiveChunks: (documentId: string) => Promise<ReadonlyMap<string, string>>
  ) {}

  setConnected(connected: boolean): void {
    this.connected = connected;
    this.render();
  }

  reveal(): void {
    if (this.panel) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      this.render();
      return;
    }
    this.panel = vscode.window.createWebviewPanel(
      ReviewPanel.viewType,
      "SuperDocs Review",
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true, localResourceRoots: [] }
    );
    this.panel.onDidDispose(() => {
      this.panel = undefined;
    });
    this.panel.webview.onDidReceiveMessage((raw: unknown) => {
      void this.handleMessage(raw);
    });
    this.render();
  }

  refresh(): void {
    this.render();
  }

  dispose(): void {
    this.disposed = true;
    this.panel?.dispose();
  }

  private async handleMessage(raw: unknown): Promise<void> {
    if (!isValidIncomingMessage(raw)) return;

    const change = this.store.getChange(raw.changeId);
    if (!change) return;

    try {
      await this.dispatch(raw.action, change);
    } catch (err) {
      vscode.window.showErrorMessage(
        `SuperDocs Review: could not ${raw.action} this change — ${err instanceof Error ? err.message : String(err)}`
      );
    }
    this.render();
  }

  private async dispatch(action: IncomingAction, change: Change): Promise<void> {
    // documentId currently equals sessionId (an explicit, documented
    // placeholder — see docs/GAP_ANALYSIS.md), but reading it directly
    // off the Change is still more robust than parsing it out of turnId's
    // string format, which is an implementation detail that has already
    // changed once (see sessionWatcher.ts's buildTurn).
    const sessionId = change.documentId;

    switch (action) {
      case "approve":
        await this.store.approve(change.id, "you", { sessionId });
        return;

      case "reject": {
        if (change.source === "auto_apply") {
          const liveChunks = await this.getLiveChunks(change.documentId);
          await this.store.reject(change.id, "you", { sessionId, liveChunks });
        } else {
          await this.store.reject(change.id, "you", { sessionId });
        }
        return;
      }

      case "revert": {
        const liveChunks = await this.getLiveChunks(change.documentId);
        await this.store.revert(change.id, "you", { sessionId, liveChunks });
        return;
      }

      case "resolve-approve":
        this.store.resolveConflict(change.id, "approved", "you");
        return;

      case "resolve-reject":
        this.store.resolveConflict(change.id, "rejected", "you");
        return;
    }
  }

  private render(): void {
    if (!this.panel || this.disposed) return;

    const changesByTurn = new Map<string, Change[]>();
    for (const change of this.store.listAllChanges()) {
      const list = changesByTurn.get(change.turnId) ?? [];
      list.push(change);
      changesByTurn.set(change.turnId, list);
    }

    const turnRecords = new Map<string, TurnRecord>();
    for (const turnId of changesByTurn.keys()) {
      const record = this.store.getTurnRecord(turnId);
      if (record) turnRecords.set(turnId, record);
    }

    const body = renderWorkspaceBody({
      connected: this.connected,
      changesByTurn,
      turnRecords,
      auditRecords: this.store.auditTrail(),
    });
    const nonce = generateNonce();
    this.panel.webview.html = renderDocument(body, nonce, this.panel.webview.cspSource);
  }
}
