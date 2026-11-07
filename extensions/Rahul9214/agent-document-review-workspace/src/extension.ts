import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { Document, Packer, Paragraph, HeadingLevel } from 'docx';
import { initialState } from './fixtures';
import { canRevert, evidenceRecord, revertChange, updateChangeStatus } from './model';
import { ChangeItem, WorkspaceState } from './types';

export function activate(context: vscode.ExtensionContext) {
  context.subscriptions.push(vscode.commands.registerCommand('superdocsAgentReview.open', () => openWorkspace(context)));
}

function openWorkspace(context: vscode.ExtensionContext) {
  let state: WorkspaceState = structuredClone(initialState);
  const panel = vscode.window.createWebviewPanel(
    'superdocsAgentReview',
    'SuperDocs Agent Review',
    vscode.ViewColumn.One,
    { enableScripts: true, retainContextWhenHidden: true }
  );
  context.subscriptions.push(panel);

  const render = () => { panel.webview.html = getHtml(state); };
  render();

  panel.webview.onDidReceiveMessage(async message => {
    if (message.type === 'select' && state.changes.some(change => change.id === message.id)) {
      state = { ...state, selectedChangeId: message.id };
      render();
      return;
    }
    if (message.type === 'decision') {
      state = updateChangeStatus(state, message.id, message.status);
      render();
      return;
    }
    if (message.type === 'revert') {
      state = revertChange(state, message.id);
      render();
      return;
    }
    if (message.type === 'reset') {
      state = structuredClone(initialState);
      render();
      return;
    }
    if (message.type === 'exportEvidence') {
      const uri = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd(), 'superdocs-review-evidence.json')) });
      if (uri) {
        fs.writeFileSync(uri.fsPath, JSON.stringify(evidenceRecord(state), null, 2), 'utf8');
        vscode.window.showInformationMessage(`Evidence exported: ${path.basename(uri.fsPath)}`);
      }
      return;
    }
    if (message.type === 'exportDocx') {
      const approved = state.changes.filter(c => c.status === 'approved' || c.status === 'applied');
      const doc = new Document({ sections: [{ children: [
        new Paragraph({ text: 'Reviewed Vendor Agreement — Demo Export', heading: HeadingLevel.TITLE }),
        new Paragraph('This synthetic artifact demonstrates the review/export state used by the workspace.'),
        ...approved.map(c => new Paragraph(`${c.section}: ${c.artifactState}`))
      ] }] });
      const buffer = await Packer.toBuffer(doc);
      const uri = await vscode.window.showSaveDialog({ defaultUri: vscode.Uri.file(path.join(vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? process.cwd(), 'reviewed-vendor-agreement.docx')) });
      if (uri) {
        fs.writeFileSync(uri.fsPath, buffer);
        vscode.window.showInformationMessage(`DOCX exported: ${path.basename(uri.fsPath)}`);
      }
    }
  });
}

function esc(value: string) {
  return value.replace(/[&<>\"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c] ?? c));
}

function groupedChanges(changes: ChangeItem[]) {
  const groups: { agent: string; turn: number; items: ChangeItem[] }[] = [];
  for (const change of changes) {
    const last = groups[groups.length - 1];
    if (!last || last.agent !== change.agent || last.turn !== change.turn) {
      groups.push({ agent: change.agent, turn: change.turn, items: [change] });
    } else {
      last.items.push(change);
    }
  }
  return groups;
}

function getHtml(state: WorkspaceState) {
  const selected = state.changes.find(c => c.id === state.selectedChangeId) ?? state.changes[0];
  const pending = state.changes.filter(c => c.status === 'pending').length;
  const mismatch = state.changes.filter(c => c.verification === 'mismatch').length;
  const same = selected.before === selected.after;
  const reviewStep = pending
    ? { mark: '◉', title: 'Proposed changes', detail: 'Waiting on human review' }
    : { mark: '✓', title: 'Review complete', detail: 'Human decisions recorded' };
  const exportStep = pending
    ? { mark: '○', title: 'Export', detail: 'Blocked until review completes' }
    : { mark: '◉', title: 'Export', detail: 'Ready for evidence export' };

  const changeRows = groupedChanges(state.changes).map(group => `
    <div class="turn-group">
      <div class="turn-label">Turn ${group.turn} · ${esc(group.agent)}</div>
      ${group.items.map(c => `
        <button type="button" class="change-row ${c.id === selected.id ? 'active' : ''}" data-id="${c.id}" ${c.id === selected.id ? 'aria-current="true"' : ''} onclick="selectChange('${c.id}')">
          <span class="agent-dot ${c.agent.includes('Cursor') ? 'cursor' : 'claude'}" aria-hidden="true"></span>
          <span class="row-main"><strong>${esc(c.section)}</strong><small>${esc(c.agent)} · Turn ${c.turn}</small></span>
          <span class="pill ${c.status}">${c.status}</span>
        </button>`).join('')}
    </div>`).join('');

  return `<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0,viewport-fit=cover"><title>SuperDocs Agent Review</title><style>
    :root{--bg:#f4f0ea;--surface:#fffcf8;--ink:#1f1c24;--muted:#5c5660;--border:#e0d9d2;--primary:#6d3cc7;--primary-soft:#f1ebfb;--coral:#c75b45;--green:#216a54;--green-soft:#eaf5f0;--red:#9e3d3d;--red-soft:#fbecec;--amber:#8a5a16;--amber-soft:#fff4e4;--shadow:0 10px 28px rgba(36,25,44,.07);--focus:0 0 0 3px rgba(109,60,199,.34);--ease:150ms ease}
    *{box-sizing:border-box}html,body{margin:0;overflow-x:hidden;height:100%}body{background:var(--bg);color:var(--ink);font:15px/1.5 "Segoe UI",ui-sans-serif,system-ui,sans-serif}
    button{font:inherit}h1,h2,p{margin:0}.app{height:100%;display:grid;grid-template-rows:auto minmax(0,1fr) auto}
    .topbar,.bottom{background:#fbfaf8;background:color-mix(in srgb,#fbfaf8 84%,transparent);backdrop-filter:saturate(1.15) blur(12px);-webkit-backdrop-filter:saturate(1.15) blur(12px)}
    .topbar{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 18px;border-bottom:1px solid var(--border)}
    .brand{display:flex;align-items:center;gap:10px;min-width:0}.brand-mark{width:30px;height:30px;border-radius:9px;background:linear-gradient(145deg,var(--primary),#a46ce4);display:grid;place-items:center;color:#fff;font-weight:700;flex:none}
    .brand-title{font-size:15px;font-weight:700;line-height:1.2}.brand-sub{color:var(--muted);font-size:12px;line-height:1.35}
    .top-stats{display:flex;flex-wrap:wrap;gap:8px;justify-content:flex-end}.chip{border:1px solid var(--border);border-radius:999px;padding:6px 10px;background:var(--surface);color:var(--muted);font-size:12px}.chip strong{color:var(--ink);font-weight:700}.chip-short,.btn-short{display:none}.chip.alert{border-color:#efb1a3;color:#8a3a2a;background:#fff4f0}
    .workspace{display:grid;grid-template-columns:minmax(240px,280px) minmax(0,1fr) minmax(260px,320px);min-width:0;min-height:0}
    .rail,.inspector{background:#f7f3ee;overflow:auto;min-width:0}.rail{border-right:1px solid var(--border);padding:16px}.inspector{border-left:1px solid var(--border);padding:16px}
    .eyebrow{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);font-weight:700;margin:0 0 8px}
    .run-card{border:1px solid var(--border);background:var(--surface);border-radius:12px;padding:13px;margin:0 0 16px;box-shadow:0 4px 12px rgba(28,21,32,.04)}.run-title{display:flex;align-items:center;justify-content:space-between;gap:8px}
    .status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 4px var(--green-soft);flex:none}
    .timeline{margin-top:10px;display:grid;gap:8px}.step{display:flex;gap:8px;color:var(--muted);font-size:12px;line-height:1.4}.step strong{color:var(--ink);font-weight:600}
    .turn-group{display:grid;gap:6px;margin-bottom:12px}.turn-label{font-size:11px;font-weight:700;color:var(--muted);letter-spacing:.04em;padding:2px 4px}
    .change-row{width:100%;min-height:44px;border:1px solid transparent;background:transparent;border-radius:12px;padding:8px 10px;text-align:left;display:grid;grid-template-columns:10px minmax(0,1fr) auto;gap:9px;align-items:center;color:var(--ink);cursor:pointer;transition:background-color var(--ease),border-color var(--ease),box-shadow var(--ease)}
    .change-row:hover{background:var(--surface);border-color:var(--border)}.change-row.active{background:var(--primary-soft);border-color:#d7c5f4}
    .change-row:focus-visible,.btn:focus-visible{outline:none;box-shadow:var(--focus)}
    .row-main{display:grid;gap:2px;min-width:0}.row-main strong{font-size:13px;overflow-wrap:anywhere}.row-main small{color:var(--muted);font-size:11px;line-height:1.35;overflow-wrap:anywhere}
    .agent-dot{width:8px;height:8px;border-radius:50%}.cursor{background:var(--primary)}.claude{background:var(--coral)}
    .pill{border-radius:999px;padding:4px 8px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;background:#eee;white-space:nowrap}
    .pill.pending{background:var(--amber-soft);color:var(--amber)}.pill.approved,.pill.applied{background:var(--green-soft);color:var(--green)}.pill.rejected,.pill.reverted{background:var(--red-soft);color:var(--red)}
    .main{padding:20px 24px;overflow:auto;min-width:0}.main-head{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;margin-bottom:16px}
    .doc-title{font-size:22px;font-weight:700;line-height:1.25;overflow-wrap:anywhere}.doc-meta{color:var(--muted);font-size:12px;margin-top:4px;overflow-wrap:anywhere}.counter{color:var(--muted);font-size:12px;flex:none}
    .diff-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);border:1px solid var(--border);border-radius:14px;overflow:hidden;background:var(--surface);box-shadow:var(--shadow)}
    .pane{padding:16px 18px;min-height:220px;min-width:0}.pane+.pane{border-left:1px solid var(--border)}.pane.before{background:#fff8f5}.pane.after{background:#f6fbf8}
    .pane-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:var(--muted);margin-bottom:14px}
    .doc-block{font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;font-size:17px;line-height:1.7;overflow-wrap:anywhere}
    .deleted{background:#fde8e3;text-decoration:line-through;text-decoration-color:#cf7665;border-radius:4px;padding:2px 4px}.added{background:#dff3e8;border-radius:4px;padding:2px 4px}.unchanged{background:#f3efe9;border-radius:4px;padding:2px 4px}
    .context{margin-top:16px;border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:14px}.context h2{margin:0 0 6px;font-size:13px}.context p{margin:0;color:var(--muted);font-size:13px}
    .verify-card{border:1px solid var(--border);border-radius:12px;background:var(--surface);padding:14px;box-shadow:0 4px 12px rgba(28,21,32,.04)}
    .verify-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}
    .verify-badge{border-radius:999px;padding:4px 8px;font-size:11px;font-weight:700;white-space:nowrap}.verify-badge.verified{background:var(--green-soft);color:var(--green)}.verify-badge.mismatch{background:var(--red-soft);color:var(--red)}
    .quote{background:#f3efe9;border-radius:10px;padding:10px;margin:6px 0 12px;color:#4f4952;overflow-wrap:anywhere}
    .meta-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:8px;margin-top:12px}.meta{border-top:1px solid var(--border);padding-top:8px;overflow-wrap:anywhere}.meta small{display:block;color:var(--muted);font-size:11px}
    .bottom{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:10px 18px;border-top:1px solid var(--border);box-shadow:0 -8px 22px rgba(36,25,44,.05)}.action-stack,.review-actions,.utility-actions{display:flex;flex-wrap:wrap;gap:8px;align-items:center}.review-actions:empty{display:none}.utility-actions{order:-1}
    .btn{border:1px solid var(--border);background:var(--surface);color:var(--ink);min-height:44px;padding:10px 14px;border-radius:10px;cursor:pointer;font-weight:600;transition:background-color var(--ease),border-color var(--ease),color var(--ease),box-shadow var(--ease)}
    .btn:hover{background:#fff}.btn:active{background:#f3eee8}.btn.primary{background:var(--primary);border-color:var(--primary);color:#fff}.btn.primary:hover{background:#5d30b4}.btn.primary:active{background:#5429a3}.btn.danger{color:var(--red)}.btn.ghost{background:transparent}
    .decision-summary{font-size:12px;color:var(--muted);max-width:36ch;line-height:1.4}
    @media(max-width:1023px){.workspace{grid-template-columns:minmax(220px,260px) minmax(0,1fr);grid-template-areas:"rail main" "rail inspector"}.rail{grid-area:rail}.main{grid-area:main}.inspector{grid-area:inspector;border-left:0;border-top:1px solid var(--border);max-height:46vh}}
    @media(max-width:767px){.workspace{grid-template-columns:minmax(0,1fr);grid-template-areas:"rail" "main" "inspector";overflow:auto}.rail{border-right:0;border-bottom:1px solid var(--border);max-height:none}.inspector{max-height:none}.diff-grid{grid-template-columns:minmax(0,1fr)}.pane+.pane{border-left:0;border-top:1px solid var(--border)}.decision-summary{max-width:none}}
    @media(max-width:639px){.topbar{display:grid;grid-template-columns:minmax(0,1fr);gap:10px;padding:12px 16px;align-items:start}.top-stats{justify-content:flex-start;gap:6px}.chip{padding:5px 9px;font-size:11px}.chip-full{display:none}.chip-short{display:inline}.btn-full{display:none}.btn-short{display:inline}.bottom{display:grid;gap:10px;padding:10px 16px calc(12px + env(safe-area-inset-bottom,0px))}.decision-summary{font-size:11px;line-height:1.4}.action-stack{display:grid;gap:8px;width:100%}.review-actions{display:flex;gap:8px;order:-1}.review-actions:empty{display:none}.review-actions .btn{flex:1;min-width:0}.review-actions .btn.primary{flex:1.35;white-space:nowrap}.utility-actions{display:flex;gap:6px;order:0}.utility-actions .btn{flex:1;min-width:0;min-height:44px;padding:8px 8px;font-size:12px;font-weight:600;color:var(--muted);background:transparent}.utility-actions .btn:hover{color:var(--ink);background:var(--surface)}}
    @media(max-width:359px){.brand-sub{display:none}.main{padding:16px}}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{transition:none!important;animation:none!important}}
  </style></head><body>
  <div class="app">
    <header class="topbar"><div class="brand"><div class="brand-mark" aria-hidden="true">S</div><div><h1 class="brand-title">SuperDocs Agent Review</h1><p class="brand-sub">Human control for agent-driven document changes</p></div></div><div class="top-stats" aria-label="Review counts"><span class="chip" aria-label="${state.documents.length} documents"><strong>${state.documents.length}</strong> <span class="chip-full">documents</span><span class="chip-short">docs</span></span><span class="chip" aria-label="${pending} pending"><strong>${pending}</strong> pending</span><span class="chip alert" aria-label="${mismatch} mismatches"><strong>${mismatch}</strong> <span class="chip-full">mismatches</span><span class="chip-short">mismatches</span></span></div></header>
    <div class="workspace">
      <nav class="rail" aria-label="Agent run and change queue"><h2 class="eyebrow">Agent run</h2><div class="run-card"><div class="run-title"><strong>${esc(selected.agent)}</strong><span class="status-dot" aria-hidden="true"></span></div><div class="timeline"><div class="step">✓ <span><strong>Opened document</strong><br>${esc(selected.documentId)}.docx</span></div><div class="step">✓ <span><strong>Located target</strong><br>${esc(selected.section)}</span></div><div class="step">${reviewStep.mark} <span><strong>${reviewStep.title}</strong><br>${reviewStep.detail}</span></div><div class="step">${exportStep.mark} <span><strong>${exportStep.title}</strong><br>${exportStep.detail}</span></div></div></div><h2 class="eyebrow">Changes</h2><div class="change-list">${changeRows}</div></nav>
      <main class="main"><div class="main-head"><div><div class="eyebrow">Document change</div><h2 class="doc-title">${esc(state.documents.find(d => d.id === selected.documentId)?.name ?? selected.documentId)}</h2><div class="doc-meta">${esc(selected.section)} · ${esc(selected.agent)} · Turn ${selected.turn}</div></div><div class="counter">${state.changes.indexOf(selected) + 1} / ${state.changes.length}</div></div>
      <div class="diff-grid"><section class="pane before"><div class="pane-label">Before</div><div class="doc-block"><span class="${same ? 'unchanged' : 'deleted'}">${esc(selected.before)}</span></div></section><section class="pane after"><div class="pane-label">${same ? 'After · no artifact change' : 'After'}</div><div class="doc-block"><span class="${same ? 'unchanged' : 'added'}">${esc(selected.after)}</span></div></section></div>
      <div class="context"><h2>Review scope</h2><p>Only this proposed section is in scope. Approving, rejecting, or reverting it does not change the other review items.</p></div></main>
      <aside class="inspector" aria-label="Claim versus actual verification"><h2 class="eyebrow">Verification</h2><div class="verify-card"><div class="verify-head"><strong>Claim vs actual</strong><span class="verify-badge ${selected.verification}">${selected.verification === 'verified' ? 'Verified' : 'Mismatch'}</span></div><small>Agent claim</small><div class="quote">${esc(selected.claim)}</div><small>Artifact check</small><div class="quote">${esc(selected.actual)}</div><small>Working artifact</small><div class="quote">${esc(selected.artifactState)}</div><div class="meta-grid"><div class="meta"><small>Agent</small>${esc(selected.agent)}</div><div class="meta"><small>Decision</small>${esc(selected.status)}</div><div class="meta"><small>Document</small>${esc(selected.documentId)}</div><div class="meta"><small>Turn</small>${selected.turn}</div></div></div></aside>
    </div>
    <footer class="bottom"><p class="decision-summary">Review is explicit. Revert appears only after a change is approved or applied.</p><div class="action-stack"><div class="review-actions" role="group" aria-label="Review decisions">${selected.status === 'pending' ? `<button type="button" class="btn danger" onclick="decision('rejected')">Reject</button><button type="button" class="btn primary" onclick="decision('approved')">Approve &amp; continue</button>` : ''}${canRevert(selected) ? `<button type="button" class="btn" onclick="revertSelected()">Revert</button>` : ''}</div><div class="utility-actions" role="group" aria-label="Demo utilities"><button type="button" class="btn ghost" onclick="send('reset')" aria-label="Reset demo"><span class="btn-full">Reset demo</span><span class="btn-short">Reset</span></button><button type="button" class="btn" onclick="send('exportEvidence')" aria-label="Export evidence"><span class="btn-full">Export evidence</span><span class="btn-short">Evidence</span></button><button type="button" class="btn" onclick="send('exportDocx')" aria-label="Export DOCX"><span class="btn-full">Export DOCX</span><span class="btn-short">DOCX</span></button></div></div></footer>
  </div>
  <script>const vscode=acquireVsCodeApi();function send(type){vscode.postMessage({type})}function selectChange(id){vscode.postMessage({type:'select',id})}function decision(status){vscode.postMessage({type:'decision',id:'${selected.id}',status})}function revertSelected(){vscode.postMessage({type:'revert',id:'${selected.id}'})}document.addEventListener('keydown',e=>{if(e.key!=='ArrowDown'&&e.key!=='ArrowUp')return;if(!e.target.closest('.change-row,.change-list'))return;e.preventDefault();const ids=${JSON.stringify(state.changes.map(c => c.id))};const i=ids.indexOf('${selected.id}');const n=ids[e.key==='ArrowDown'?Math.min(i+1,ids.length-1):Math.max(i-1,0)];if(n)selectChange(n)});</script>
  </body></html>`;
}

export function deactivate() {}
