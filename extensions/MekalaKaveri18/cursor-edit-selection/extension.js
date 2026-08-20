const vscode = require("vscode");
const https = require("https");
const http = require("http");
const { URL } = require("url");
const { wrapSelection, instructionFor } = require("./lib");

function postJson(urlString, apiKey, body) {
  return new Promise((resolve, reject) => {
    const url = new URL(urlString);
    const lib = url.protocol === "http:" ? http : https;
    const req = lib.request(
      {
        hostname: url.hostname,
        port: url.port,
        path: url.pathname,
        method: "POST",
        headers: {
          Authorization: `Bearer ${apiKey}`,
          "Content-Type": "application/json",
        },
      },
      (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          if (res.statusCode && res.statusCode >= 400) {
            reject(new Error(data || String(res.statusCode)));
            return;
          }
          try {
            resolve(JSON.parse(data || "{}"));
          } catch (e) {
            reject(e);
          }
        });
      }
    );
    req.on("error", reject);
    req.write(JSON.stringify(body));
    req.end();
  });
}

async function editSelection() {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showErrorMessage("No active editor.");
    return;
  }
  const sel = editor.selection;
  const text = editor.document.getText(sel);
  if (!text.trim()) {
    vscode.window.showErrorMessage("Select the passage SuperDocs should edit.");
    return;
  }
  const how = await vscode.window.showInputBox({
    prompt: "What should SuperDocs change in this selection?",
  });
  if (!how) return;
  const cfg = vscode.workspace.getConfiguration("superdocs");
  const key = cfg.get("apiKey") || process.env.SUPERDOCS_API_KEY;
  if (!key) {
    vscode.window.showErrorMessage("Set superdocs.apiKey in settings or SUPERDOCS_API_KEY.");
    return;
  }
  const base = (cfg.get("baseUrl") || "https://api.superdocs.app").replace(/\/$/, "");
  const session = "cursor-sel-" + Date.now();
  const result = await postJson(`${base}/v1/chat`, key, {
    session_id: session,
    message: instructionFor(how),
    document_html: wrapSelection(text),
    approval_mode: "approve_all",
  });
  const html =
    (result.document_changes && result.document_changes.updated_html) ||
    result.response ||
    "";
  const stripped = html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
  await editor.edit((b) => b.replace(sel, stripped || text));
}

function activate(context) {
  context.subscriptions.push(
    vscode.commands.registerCommand("superdocs.editSelection", () =>
      editSelection().catch((e) => vscode.window.showErrorMessage(String(e.message || e)))
    )
  );
}

function deactivate() {}

module.exports = { activate, deactivate };
