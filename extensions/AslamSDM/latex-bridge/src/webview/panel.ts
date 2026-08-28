import * as vscode from "vscode";
import { IngestWarning, ExportWarning, QuotaInfo } from "../core/types";

export interface AuthStatus {
  hasKey: boolean;
  error?: string;
  quota?: QuotaInfo;
}

export interface PanelHandlers {
  onGetAuthStatus: () => Promise<AuthStatus>;
  onSetApiKey: (key: string) => Promise<AuthStatus>;
  onClearApiKey: () => Promise<AuthStatus>;
  onGetWorkspaceProject: () => Promise<string | undefined>;
  onOpenProject: () => Promise<string | undefined>;
  onOpenSession: (sessionId: string) => void;
  onCreateSession: (projectDir: string) => Promise<{
    sessionId: string;
    chunksCount: number;
    warnings: IngestWarning[];
  }>;
  onRequestEdit: (message: string) => Promise<{
    response: string;
    updatedHtml: string;
  }>;
  onExportDocx: (filename: string) => Promise<{
    saved: boolean;
    path?: string;
    warnings: ExportWarning[];
  }>;
  onSubmitDecisions: (decisions: { changeId: string; approved: boolean }[]) => void;
  onWriteBack: (changes: { changeId: string; chunkId: string; oldHtml: string; newHtml: string }[]) => Promise<{
    applied: number;
    total: number;
    unresolved: number;
  }>;
}

interface WebviewMessage {
  type: string;
  [key: string]: unknown;
}

export class ChatViewProvider implements vscode.WebviewViewProvider {
  public static readonly viewType = "latexBridge.chat";

  /** Called after the webview HTML is loaded — lets the host (re)wire handlers and push auth status. */
  onResolved: (() => void) | undefined;

  private view: vscode.WebviewView | undefined;
  private queued: { type: string; payload: unknown }[] = [];
  private handlers: PanelHandlers | undefined;

  constructor(private readonly context: vscode.ExtensionContext) {}

  resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;

    view.webview.options = {
      enableScripts: true,
      localResourceRoots: [vscode.Uri.joinPath(this.context.extensionUri, "dist")],
    };

    const media = vscode.Uri.joinPath(this.context.extensionUri, "dist", "media");
    view.webview.html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src ${view.webview.cspSource} 'unsafe-inline'; img-src ${view.webview.cspSource} https: data:; script-src ${view.webview.cspSource};">
<link rel="stylesheet" href="${view.webview.asWebviewUri(vscode.Uri.joinPath(media, "app.css"))}">
</head>
<body>
<div id="root"></div>
<script src="${view.webview.asWebviewUri(vscode.Uri.joinPath(this.context.extensionUri, "dist", "webview", "app.js"))}"></script>
</body>
</html>`;

    view.webview.onDidReceiveMessage((msg: WebviewMessage) => this.onMessage(msg));

    view.onDidDispose(() => {
      this.view = undefined;
    });

    const flush = this.queued;
    this.queued = [];
    for (const { type, payload } of flush) this.emit(type, payload);

    this.onResolved?.();
  }

  private async onMessage(msg: WebviewMessage): Promise<void> {
    if (!this.handlers) return;
    try {
      switch (msg.type) {
        case "getAuthStatus": {
          const status = await this.handlers.onGetAuthStatus();
          this.post({ type: "authStatus", ...status });
          break;
        }
        case "setApiKey": {
          const status = await this.handlers.onSetApiKey(msg.key as string);
          this.post({ type: "authStatus", ...status });
          break;
        }
        case "clearApiKey": {
          const status = await this.handlers.onClearApiKey();
          this.post({ type: "authStatus", ...status });
          break;
        }
        case "openExternal": {
          const url = msg.url as string;
          if (url && /^https:\/\//.test(url)) {
            void vscode.env.openExternal(vscode.Uri.parse(url));
          }
          break;
        }
        case "openProject": {
          const dir = await this.handlers.onOpenProject();
          this.post({ type: "projectOpened", path: dir ?? null });
          break;
        }
        case "getWorkspaceProject": {
          const dir = await this.handlers.onGetWorkspaceProject();
          this.post({ type: "workspaceProject", path: dir ?? null });
          break;
        }
        case "createSession": {
          const dir = msg.projectDir as string;
          const info = await this.handlers.onCreateSession(dir);
          this.post({ type: "sessionCreated", ...info });
          break;
        }
        case "openSession": {
          this.handlers.onOpenSession(msg.sessionId as string);
          this.post({ type: "sessionOpened", sessionId: msg.sessionId });
          break;
        }
        case "requestEdit": {
          this.post({ type: "editStarted" });
          const result = await this.handlers.onRequestEdit(msg.message as string);
          this.post({ type: "editCompleted", ...result });
          break;
        }
        case "exportDocx": {
          const result = await this.handlers.onExportDocx((msg.filename as string) ?? "");
          this.post({ type: "exportCompleted", ...result });
          break;
        }
        case "submitDecisions": {
          this.handlers.onSubmitDecisions((msg.decisions as { changeId: string; approved: boolean }[]) ?? []);
          this.post({ type: "decisionsSubmitted" });
          break;
        }
        case "writeBack": {
          const changes = (msg.changes as { changeId: string; chunkId: string; oldHtml: string; newHtml: string }[]) ?? [];
          const result = await this.handlers.onWriteBack(changes);
          this.post({ type: "writeBackResult", ...result });
          break;
        }
        default:
          break;
      }
    } catch (err) {
      this.post({ type: "error", message: err instanceof Error ? err.message : String(err) });
    }
  }

  private post(message: unknown): void {
    if (this.view) {
      void this.view.webview.postMessage(message);
    }
  }

  ready(h: PanelHandlers): void {
    this.handlers = h;
    this.emit("ready", { sessionId: "" });
  }

  emit(type: string, payload: unknown): void {
    if (!this.view) {
      this.queued.push({ type, payload });
      return;
    }
    this.post({ type, ...(payload as Record<string, unknown>) });
  }
}
