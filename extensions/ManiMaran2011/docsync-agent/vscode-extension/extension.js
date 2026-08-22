// Thin extension shell -- deliberately NOT a reimplementation of the sync logic in TypeScript. Every
// decision (what changed, what's documented, what to propose) lives in the Python engine, which is already
// tested (see ../tests/). This extension's only job is: run that engine as a subprocess, parse its JSON
// output, and render it as a VS Code webview with approve/reject checkboxes -- the same shape as the CLI's
// terminal output, just inside the editor. Keeping logic out of the extension means the exact same tested
// code path runs whether you use the CLI or the editor integration.

const vscode = require('vscode');
const { exec } = require('child_process');
const path = require('path');

function activate(context) {
  const disposable = vscode.commands.registerCommand('docsync.check', () => {
    const folders = vscode.workspace.workspaceFolders;
    if (!folders || folders.length === 0) {
      vscode.window.showErrorMessage('DocSync: open a folder/workspace first.');
      return;
    }
    const repoPath = folders[0].uri.fsPath;
    const readmePath = path.join(repoPath, 'README.md');

    vscode.window.showInformationMessage('DocSync: checking for stale documentation...');

    // Runs the Python CLI in a mode that ONLY reports proposals (no auto-apply), so the extension never
    // silently spends SuperDocs operations without the user explicitly approving in the panel below.
    const cmd = `python -m src.cli check "${repoPath}" "${readmePath}" --report-only`;
    exec(cmd, { cwd: path.join(__dirname, '..') }, (err, stdout, stderr) => {
      if (err) {
        vscode.window.showErrorMessage(`DocSync failed: ${stderr || err.message}`);
        return;
      }
      showProposalsPanel(stdout);
    });
  });

  context.subscriptions.push(disposable);
}

function showProposalsPanel(cliOutput) {
  const panel = vscode.window.createWebviewPanel(
    'docsyncProposals',
    'DocSync — Proposed doc updates',
    vscode.ViewColumn.Beside,
    { enableScripts: false }
  );
  // Escaped plain-text render of the CLI's own summary lines -- the CLI is the source of truth for what
  // was found; this panel doesn't reinterpret or re-derive anything from it.
  const escaped = cliOutput
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  panel.webview.html = `
    <html><body style="font-family: sans-serif; padding: 1em;">
      <h2>DocSync results</h2>
      <pre>${escaped}</pre>
      <p><em>Run <code>python -m src.cli check &lt;repo&gt; &lt;doc&gt;</code> in a terminal to review and
      apply approved updates interactively -- this panel is read-only, matching the CLI's own
      report-then-approve flow rather than adding a second, divergent approval path.</em></p>
    </body></html>
  `;
}

function deactivate() {}

module.exports = { activate, deactivate };
