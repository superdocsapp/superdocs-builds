import * as vscode from "vscode";
import { parseChunks } from "./chunkDiff";
import { LiveSuperDocsSideEffects } from "./liveSideEffects";
import { JsonFileBackend } from "./persistence";
import { ReviewPanel } from "./reviewPanel";
import { ReviewStore } from "./reviewStore";
import { SessionWatcher } from "./sessionWatcher";
import { SuperDocsClient } from "./superdocsClient";
import { TurnsTreeProvider } from "./turnsTreeProvider";

const SECRET_KEY = "superdocsAgentReview.apiKey";

export function activate(context: vscode.ExtensionContext): void {
  // --- persistence & core engine -------------------------------------
  // A real on-disk store, not in-memory: pending review state must
  // survive an extension host restart (VS Code reload, machine restart).
  const backend = new JsonFileBackend(vscode.Uri.joinPath(context.globalStorageUri, "review-store").fsPath);

  let store: ReviewStore | undefined;
  let client: SuperDocsClient | undefined;
  let watcher: SessionWatcher | undefined;

  const treeProvider = new TurnsTreeProvider(undefined);
  const treeView = vscode.window.createTreeView("superdocsAgentReview.turns", { treeDataProvider: treeProvider });
  context.subscriptions.push(treeView);

  let panel: ReviewPanel | undefined;

  async function getLiveChunks(documentId: string): Promise<ReadonlyMap<string, string>> {
    if (!client) throw new Error("Not connected to SuperDocs.");
    // documentId is resolved via resolveDocumentId() (sessionWatcher.ts),
    // currently a stand-in equal to sessionId — see that function's
    // docstring and docs/IMPLEMENTATION_PLAN.md §15 for the known gap.
    const history = await client.getSessionHistory(documentId);
    const html = history.document_state?.html;
    if (html === undefined) throw new Error(`No live document state for session ${documentId}.`);
    return parseChunks(html);
  }

  function wireConnectedServices(apiKey: string): void {
    client = new SuperDocsClient({ apiKey });
    store = new ReviewStore(backend, new LiveSuperDocsSideEffects(client));
    watcher = new SessionWatcher(client, store, {
      persistence: backend,
      onError: (err, context) => {
        console.error("SuperDocs Review: poll failed", context.sessionId ? `(session ${context.sessionId})` : "", err);
      },
    });
    watcher.start();

    panel = new ReviewPanel(store, getLiveChunks);
    panel.setConnected(true);

    treeProvider.setConnected(true);
    // Re-render the tree on a light interval tied to the same cadence as
    // polling, since TurnsTreeProvider has no direct subscription to the
    // store (the store is a plain class, not an event emitter — kept
    // deliberately simple; see docs/IMPLEMENTATION_PLAN.md known limitations
    // for the tradeoff).
    const refreshTimer = setInterval(() => {
      treeProvider.refresh();
      panel?.refresh();
    }, 4000);
    context.subscriptions.push({ dispose: () => clearInterval(refreshTimer) });
  }

  // --- commands --------------------------------------------------------

  context.subscriptions.push(
    vscode.commands.registerCommand("superdocsAgentReview.connect", async () => {
      const apiKey = await vscode.window.showInputBox({
        title: "Connect your SuperDocs account",
        prompt:
          "Paste a SuperDocs API key (starts with sk_ or lce_). Stored in VS Code's encrypted SecretStorage — never written to settings or source control.",
        password: true,
        ignoreFocusOut: true,
        validateInput: (value) =>
          value.startsWith("sk_") || value.startsWith("lce_")
            ? null
            : "SuperDocs API keys start with sk_ (personal) or lce_ (organization).",
      });
      if (!apiKey) return;

      const probe = new SuperDocsClient({ apiKey });
      try {
        await probe.healthCheckKey();
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err);
        vscode.window.showErrorMessage(`Could not connect to SuperDocs: ${message}`);
        return;
      }

      await context.secrets.store(SECRET_KEY, apiKey);
      wireConnectedServices(apiKey);
      vscode.window.showInformationMessage("SuperDocs account connected.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("superdocsAgentReview.disconnect", async () => {
      await context.secrets.delete(SECRET_KEY);
      watcher?.stop();
      watcher = undefined;
      client = undefined;
      treeProvider.setConnected(false);
      panel?.setConnected(false);
      vscode.window.showInformationMessage("Disconnected from SuperDocs.");
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("superdocsAgentReview.refresh", async () => {
      await watcher?.pollOnce();
      treeProvider.refresh();
      panel?.refresh();
    })
  );

  context.subscriptions.push(
    vscode.commands.registerCommand("superdocsAgentReview.openPanel", () => {
      if (!panel) {
        vscode.window.showWarningMessage("Connect a SuperDocs account first.");
        return;
      }
      panel.reveal();
    })
  );

  context.subscriptions.push({
    dispose: () => {
      watcher?.stop();
      panel?.dispose();
    },
  });

  // --- restore prior connection on activation --------------------------
  void context.secrets.get(SECRET_KEY).then((existing) => {
    if (existing) {
      wireConnectedServices(existing);
    } else {
      treeProvider.setConnected(false);
    }
  });
}

export function deactivate(): void {
  // All timers and the watcher's polling interval are owned by
  // `context.subscriptions` (registered as disposables above), so VS Code
  // disposing the extension host already stops them — nothing additional
  // to release here.
}
