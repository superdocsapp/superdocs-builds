import * as vscode from "vscode";
import { SuperDocsClient } from "./core/client";
import { BridgeSession, sessionIdFor } from "./core/session";
import { findLaTeXRoot, buildProjectZip, ProjectInfo } from "./core/zip";
import { writeBackToProject } from "./core/writeback-cli";
import { parseDocxTrackChanges, toChange } from "./core/trackchanges";
import { initKeyStorage, getKey, setKey, clearKey } from "./keychain";
import { ChatViewProvider } from "./webview/panel";

async function quotaOf(client: SuperDocsClient) {
  const timeout = new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 8000));
  try {
    return await Promise.race([client.whoami(), timeout]);
  } catch {
    return undefined;
  }
}

interface PersistedState {
  projectDir?: string;
  workspaceDir?: string;
  sessionId?: string;
}

export function activate(context: vscode.ExtensionContext): void {
  initKeyStorage(context.secrets);
  const state: PersistedState = {
    projectDir: context.workspaceState.get("latexBridge.projectDir"),
    workspaceDir: context.workspaceState.get("latexBridge.workspaceDir"),
    sessionId: context.workspaceState.get("latexBridge.sessionId"),
  };

  async function patchProject(
    dir: string,
    changes: { changeId: string; chunkId: string; oldHtml: string; newHtml: string }[]
  ): Promise<{ applied: number; total: number; unresolved: number }> {
    const root = findLaTeXRoot(dir);
    if (!root) throw new Error("No LaTeX root found in this folder.");
    const result = await writeBackToProject(
      dir,
      root,
      changes.map((c) => ({
        change_id: c.changeId,
        chunk_id: c.chunkId,
        operation: "edit",
        old_html: c.oldHtml,
        new_html: c.newHtml,
      }))
    );
    let patched = 0;
    for (const [file, content] of result.files) {
      const target = vscode.Uri.joinPath(vscode.Uri.file(dir), file);
      await vscode.workspace.fs.writeFile(target, Buffer.from(content, "utf8"));
      patched += 1;
    }
    return {
      applied: result.applied.length,
      total: changes.length,
      unresolved: result.unresolved.length,
    };
  }

  const viewProvider = new ChatViewProvider(context);
  viewProvider.onResolved = () => {
    wirePanel();
    void pushAuthStatus();
  };
  context.subscriptions.push(
    vscode.window.registerWebviewViewProvider(ChatViewProvider.viewType, viewProvider, {
      webviewOptions: { retainContextWhenHidden: true },
    })
  );

  let activeSession: BridgeSession | undefined;
  let client: SuperDocsClient | undefined;

  async function makeClient(): Promise<SuperDocsClient | undefined> {
    const key = await getKey();
    if (!key) {
      const entered = await vscode.window.showInputBox({
        prompt: "Enter your SuperDocs API key (sk_...) — stored in VS Code secret storage",
        password: true,
      });
      if (!entered) return undefined;
      await setKey(entered);
      return new SuperDocsClient(entered, {
        pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
      });
    }
    return new SuperDocsClient(key, {
      pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
    });
  }

  async function openPanel(): Promise<void> {
    if (!client) client = await makeClient();
    if (!client) return;
    await vscode.commands.executeCommand("latexBridge.chat.focus");
    wirePanel();
    await pushAuthStatus();
  }

  async function pushAuthStatus(): Promise<void> {
    const key = await getKey();
    const status: { hasKey: boolean; quota?: unknown } = { hasKey: key !== undefined };
    if (key) {
      if (!client) {
        client = new SuperDocsClient(key, {
          pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
        });
      }
      const timeout = new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 8000));
      try {
        status.quota = await Promise.race([client.whoami(), timeout]);
      } catch {
        /* transient — keep hasKey only */
      }
    }
    viewProvider.emit("authStatus", status);
  }

  function wirePanel(): void {
    const provider = viewProvider;
    if (!provider) return;
    provider.ready({
      onGetAuthStatus: async () => {
        const key = await getKey();
        if (!key) return { hasKey: false };
        if (!client) {
          client = new SuperDocsClient(key, {
            pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
          });
        }
        return { hasKey: true, quota: await quotaOf(client) };
      },
      onSetApiKey: async (key: string) => {
        await setKey(key.trim());
        client = new SuperDocsClient(key.trim(), {
          pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
        });
        return { hasKey: true, quota: await quotaOf(client) };
      },
      onClearApiKey: async () => {
        await clearKey();
        client = undefined;
        return { hasKey: false };
      },
      onOpenProject: async () => {
        const dir = await vscode.window.showOpenDialog({
          canSelectFiles: false,
          canSelectFolders: true,
          canSelectMany: false,
          title: "Select your LaTeX project folder (Overleaf export shape)",
        });
        return dir?.[0]?.fsPath;
      },
      onGetWorkspaceProject: async () => {
        const folders = vscode.workspace.workspaceFolders;
        if (!folders || folders.length === 0) return undefined;
        const dir = folders[0].uri.fsPath;
        if (!findLaTeXRoot(dir)) return undefined;
        state.workspaceDir = dir;
        context.workspaceState.update("latexBridge.workspaceDir", dir);
        return dir;
      },
      onOpenSession: (sessionId: string) => {
        state.sessionId = sessionId;
        context.workspaceState.update("latexBridge.sessionId", sessionId);
      },
      onSubmitDecisions: (decisions) => {
        if (!activeSession) return;
        activeSession.submitDecisions(decisions);
      },
      onCreateSession: async (projectDir: string) => {
        const root = findLaTeXRoot(projectDir);
        if (!root) {
          throw new Error(
            "No LaTeX root found. Expected main.tex, a % !TEX root directive, or a single .tex file."
          );
        }
        const proj: ProjectInfo = await buildProjectZip(projectDir, root);
        const sid = sessionIdFor(root);
        const session = new BridgeSession(client!, sid, {
          opBudget: vscode.workspace.getConfiguration("latexBridge").get("opBudgetPerSession", 10),
          pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
        }, (e) => viewProvider?.emit("sessionEvent", e));
        activeSession = session;
        state.sessionId = sid;
        context.workspaceState.update("latexBridge.projectDir", projectDir);
        context.workspaceState.update("latexBridge.sessionId", sid);
        const info = await session.uploadProject(proj.zipBytes, `${root.replace(/\.tex$/, "")}.zip`, "application/zip");
        return { sessionId: info.sessionId, chunksCount: info.chunksCount ?? 0, warnings: info.warnings };
      },
      onRequestEdit: async (message: string) => {
        if (!activeSession) throw new Error("No active session — upload a project first.");
        const job = await activeSession.requestEdit(message);
        return { response: job.result?.response ?? "", updatedHtml: job.result?.document_changes?.updated_html ?? "" };
      },
      onWriteBack: async (changes) => {
        const dir = state.projectDir ?? state.workspaceDir ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        if (!dir) throw new Error("No project folder selected.");
        const outcome = await patchProject(dir, changes);
        if (outcome.applied > 0) {
          vscode.window.showInformationMessage(
            `LaTeX Bridge: applied ${outcome.applied}/${outcome.total} edits` +
              (outcome.unresolved > 0 ? `; ${outcome.unresolved} could not be located` : "")
          );
        } else if (outcome.unresolved > 0) {
          vscode.window.showWarningMessage(
            `LaTeX Bridge: ${outcome.unresolved} edit(s) could not be located in the .tex sources.`
          );
        }
        return outcome;
      },
      onExportDocx: async (filename: string) => {
        if (!activeSession || !state.sessionId) throw new Error("No active session — upload a project first.");
        const result = await client!.exportDocx(state.sessionId, { paper_size: "A4" });
        const uri = await vscode.window.showSaveDialog({
          defaultUri: vscode.Uri.file(filename || "document.docx"),
          filters: { "Word Document": ["docx"] },
        });
        if (!uri) return { saved: false, warnings: result.warnings };
        await vscode.workspace.fs.writeFile(uri, result.body);
        return { saved: true, path: uri.fsPath, warnings: result.warnings };
      },
    });
  }

  context.subscriptions.push(
    vscode.commands.registerCommand("latex-bridge.open", openPanel),
    vscode.commands.registerCommand("latex-bridge.focus", () =>
      vscode.commands.executeCommand("latexBridge.chat.focus")
    ),
    vscode.commands.registerCommand("latex-bridge.uploadProject", async () => {
      const dir = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        title: "Select your LaTeX project folder",
      });
      if (!dir?.[0]) return;
      const root = findLaTeXRoot(dir[0].fsPath);
      if (!root) {
        vscode.window.showErrorMessage("LaTeX Bridge: no LaTeX root found in this folder.");
        return;
      }
      const proj = await buildProjectZip(dir[0].fsPath, root);
      client = await makeClient();
      if (!client) return;
      const sid = sessionIdFor(root);
      activeSession = new BridgeSession(client, sid, {
        opBudget: vscode.workspace.getConfiguration("latexBridge").get("opBudgetPerSession", 10),
        pollIntervalMs: vscode.workspace.getConfiguration("latexBridge").get("pollIntervalMs", 2000),
      }, () => {});
      const info = await activeSession.uploadProject(
        proj.zipBytes,
        `${root.replace(/\.tex$/, "")}.zip`,
        "application/zip"
      );
      vscode.window.showInformationMessage(
        `LaTeX Bridge: project parsed into ${info.chunksCount} editable sections.`
      );
    }),
    vscode.commands.registerCommand("latex-bridge.exportDocx", async () => {
      if (!client || !state.sessionId) {
        vscode.window.showErrorMessage("LaTeX Bridge: no active session.");
        return;
      }
      const result = await client.exportDocx(state.sessionId, { paper_size: "A4" });
      const uri = await vscode.window.showSaveDialog({
        filters: { "Word Document": ["docx"] },
      });
      if (!uri) return;
      await vscode.workspace.fs.writeFile(uri, result.body);
      vscode.window.showInformationMessage(`LaTeX Bridge: exported ${uri.fsPath}`);
    }),
    vscode.commands.registerCommand("latex-bridge.writeBack", async () => {
      if (!activeSession) {
        vscode.window.showErrorMessage("LaTeX Bridge: no active session.");
        return;
      }
      const changes = activeSession.approvedChanges;
      if (changes.length === 0) {
        vscode.window.showInformationMessage("LaTeX Bridge: no approved edits to write back yet.");
        return;
      }
      const dir = state.projectDir ?? state.workspaceDir ?? vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
      if (!dir) {
        vscode.window.showErrorMessage("LaTeX Bridge: no project folder selected.");
        return;
      }
      try {
        const outcome = await patchProject(
          dir,
          changes.map((c) => ({
            changeId: c.change_id,
            chunkId: c.chunk_id,
            oldHtml: c.old_html,
            newHtml: c.new_html,
          }))
        );
        const summary =
          `LaTeX Bridge: applied ${outcome.applied}/${outcome.total} edits` +
          (outcome.unresolved > 0 ? `; ${outcome.unresolved} could not be located` : "");
        if (outcome.unresolved > 0) {
          vscode.window.showWarningMessage(summary);
        } else {
          vscode.window.showInformationMessage(summary);
        }
      } catch (err) {
        vscode.window.showErrorMessage(`LaTeX Bridge: ${err instanceof Error ? err.message : String(err)}`);
      }
    }),
    vscode.commands.registerCommand("latex-bridge.importTrackChanges", async () => {
      const docxUri = await vscode.window.showOpenDialog({
        canSelectFiles: true,
        canSelectFolders: false,
        canSelectMany: false,
        title: "Select the co-author's .docx (with tracked changes)",
        filters: { "Word Document": ["docx"] },
      });
      if (!docxUri?.[0]) return;
      const bytes = await vscode.workspace.fs.readFile(docxUri[0]);
      const changes = await parseDocxTrackChanges(new Uint8Array(bytes));
      if (changes.length === 0) {
        vscode.window.showInformationMessage("LaTeX Bridge: no tracked changes found in this document.");
        return;
      }
      const picked = await vscode.window.showQuickPick(
        changes.map((c, i) => ({
          label: `${c.id} — ${c.author}`,
          description: c.date ?? "",
          detail: c.oldText
            ? `${c.oldText.slice(0, 120)} → ${c.newText.slice(0, 120)}`
            : `insert: ${c.newText.slice(0, 120)}`,
          change: c,
          index: i,
        })),
        {
          canPickMany: true,
          placeHolder: "Select tracked changes to apply to the LaTeX project",
        }
      );
      if (!picked || picked.length === 0) return;
      const dir = await vscode.window.showOpenDialog({
        canSelectFiles: false,
        canSelectFolders: true,
        canSelectMany: false,
        title: "Select the LaTeX project folder to patch",
      });
      if (!dir?.[0]) return;
      const root = findLaTeXRoot(dir[0].fsPath);
      if (!root) return;
      const result = await writeBackToProject(
        dir[0].fsPath,
        root,
        picked.map((p) => toChange(p.change))
      );
      let patched = 0;
      for (const [file, content] of result.files) {
        const target = vscode.Uri.joinPath(vscode.Uri.file(dir[0].fsPath), file);
        await vscode.workspace.fs.writeFile(target, Buffer.from(content, "utf8"));
        patched += 1;
      }
      const summary =
        `LaTeX Bridge: applied ${result.applied.length}/${picked.length} tracked changes across ${patched} file(s)` +
        (result.unresolved.length > 0 ? `; ${result.unresolved.length} could not be located` : "");
      if (result.unresolved.length > 0) {
        vscode.window.showWarningMessage(summary);
      } else {
        vscode.window.showInformationMessage(summary);
      }
    }),
    vscode.commands.registerCommand("latex-bridge.setKey", async () => {
      const key = await vscode.window.showInputBox({
        prompt: "SuperDocs API key (sk_...)",
        password: true,
      });
      if (key) {
        await setKey(key);
        vscode.window.showInformationMessage("LaTeX Bridge: API key stored.");
      }
    }),
    vscode.commands.registerCommand("latex-bridge.clearKey", async () => {
      await clearKey();
      vscode.window.showInformationMessage("LaTeX Bridge: API key removed.");
    })
  );

  context.subscriptions.push({
    dispose: () => {
      /* sessions are server-side; nothing to tear down locally */
    },
  });
}

export function deactivate(): void {
  /* no-op */
}
