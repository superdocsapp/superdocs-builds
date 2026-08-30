import sanitizeHtmlLib from "sanitize-html";
import type { AuditRecord, Change, ChangeStatus, ReconciliationVerdict, TurnRecord } from "./types";

export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** Same escaping is safe inside a double-quoted HTML attribute. */
export const escapeAttr = escapeHtml;

/**
 * Sanitizes a SuperDocs document HTML fragment before it's inserted into
 * the webview, using `sanitize-html` (maintained, actively used library)
 * rather than hand-rolled regex. This is defense in depth, not the primary
 * boundary — the webview's Content-Security-Policy (script-src limited to
 * one nonce, no 'unsafe-inline', no remote origins) is what actually
 * prevents any of this from executing even if sanitization were somehow
 * bypassed. The allowlist below covers ordinary document formatting
 * (headings, paragraphs, emphasis, lists, tables, links) and always keeps
 * `data-chunk-id` so the rendered fragment still shows which chunk is which;
 * everything else — scripts, iframes, event handlers, forms, embeds,
 * `javascript:`/`data:` URLs — is stripped.
 */
export function sanitizeFragment(html: string): string {
  return sanitizeHtmlLib(html, {
    allowedTags: [
      "p", "br", "hr", "span", "div",
      "h1", "h2", "h3", "h4", "h5", "h6",
      "strong", "b", "em", "i", "u", "s", "sub", "sup", "mark", "small",
      "ul", "ol", "li",
      "table", "thead", "tbody", "tfoot", "tr", "th", "td",
      "a", "blockquote", "code", "pre",
    ],
    allowedAttributes: {
      "*": ["data-chunk-id", "colspan", "rowspan", "align"],
      a: ["href", "title"],
    },
    allowedSchemes: ["http", "https", "mailto"],
    // Any URL not on an allowed scheme (javascript:, data:, etc.) is dropped
    // rather than passed through disarmed, since a dropped href is safe by
    // construction and a "cleaned" one is one regex away from a bypass.
    disallowedTagsMode: "discard",
  });
}

const VERDICT_LABEL: Record<ReconciliationVerdict, string> = {
  match: "✓ Claim / actual match",
  partial: "◐ Partial match",
  conflicting: "⚠ Conflicting — diff exists but wasn't billed as a real edit",
  claimed_not_observed: "⚠ Claimed but not observed",
  no_claim: "No change claimed",
};

const VERDICT_CLASS: Record<ReconciliationVerdict, string> = {
  match: "badge-match",
  partial: "badge-warn",
  conflicting: "badge-danger",
  claimed_not_observed: "badge-danger",
  no_claim: "badge-muted",
};

export function renderReconciliationBadge(verdict: ReconciliationVerdict): string {
  return `<span class="badge ${VERDICT_CLASS[verdict]}">${escapeHtml(VERDICT_LABEL[verdict])}</span>`;
}

const STATUS_LABEL: Record<ChangeStatus, string> = {
  proposed: "Pending review",
  approved: "Approved",
  rejected: "Rejected",
  reverted: "Reverted",
  conflicted: "Conflict — needs manual resolution",
  failed: "Failed",
  superseded: "Superseded by a later turn",
};

function renderActions(change: Change): string {
  const id = escapeAttr(change.id);
  switch (change.status) {
    case "proposed":
      return (
        `<button data-action="approve" data-change-id="${id}">Approve</button>` +
        `<button data-action="reject" data-change-id="${id}" class="secondary">Reject</button>`
      );
    case "approved":
      return `<button data-action="revert" data-change-id="${id}" class="secondary">Revert</button>`;
    case "conflicted":
      return (
        `<button data-action="resolve-approve" data-change-id="${id}">Keep current document state</button>` +
        `<button data-action="resolve-reject" data-change-id="${id}" class="secondary">Discard this change</button>`
      );
    default:
      return "";
  }
}

function renderFragmentOrPlaceholder(html: string | null, placeholder: string): string {
  if (html === null) return `<em class="placeholder">${escapeHtml(placeholder)}</em>`;
  return `<div class="doc-fragment">${sanitizeFragment(html)}</div>`;
}

export function renderChangeCard(change: Change, index: number): string {
  const badge = renderReconciliationBadge(change.reconciliation);
  const claimLine = change.aiExplanation
    ? `<p class="claim">Claimed: ${escapeHtml(change.aiExplanation)}</p>`
    : "";
  const conflictLine =
    change.status === "conflicted"
      ? `<p class="conflict-note">This chunk changed after this proposal was created — review the current state before deciding.</p>`
      : "";

  return `
<article class="change-card status-${change.status}" data-change-id="${escapeAttr(change.id)}" tabindex="0" aria-label="Change ${index + 1}, ${escapeAttr(change.operation)} on ${escapeAttr(change.chunkId ?? "new content")}, ${escapeAttr(STATUS_LABEL[change.status])}">
  <header>
    <span class="change-index">Change ${index + 1}</span>
    <span class="change-op">${escapeHtml(change.operation)}</span>
    <span class="change-chunk">${escapeHtml(change.chunkId ?? "(new)")}</span>
    ${badge}
  </header>
  ${claimLine}
  ${conflictLine}
  <div class="before-after">
    <div class="before"><h4>Before</h4>${renderFragmentOrPlaceholder(change.beforeHtml, "(none — newly created)")}</div>
    <div class="after"><h4>After</h4>${renderFragmentOrPlaceholder(change.afterHtml, "(none — removed)")}</div>
  </div>
  <footer class="actions">
    <span class="status-label">${escapeHtml(STATUS_LABEL[change.status])}</span>
    ${renderActions(change)}
  </footer>
</article>`.trim();
}

export function renderTurnSection(turnId: string, changes: Change[], turnRecord: TurnRecord | null): string {
  const pending = changes.filter((c) => c.status === "proposed").length;
  const conflicts = changes.filter((c) => c.status === "conflicted").length;
  const summary = [`${changes.length} change${changes.length === 1 ? "" : "s"}`];
  if (pending > 0) summary.push(`${pending} pending`);
  if (conflicts > 0) summary.push(`${conflicts} conflict${conflicts === 1 ? "" : "s"}`);

  const requestLine = turnRecord?.claimedIntentText
    ? `<p class="turn-request"><span class="turn-field-label">Instruction:</span> ${escapeHtml(turnRecord.claimedIntentText)}</p>`
    : "";
  const replyLine = turnRecord?.claimedResultText
    ? `<p class="turn-reply"><span class="turn-field-label">Agent reply:</span> ${escapeHtml(turnRecord.claimedResultText)}</p>`
    : "";

  return `
<section class="turn-section" data-turn-id="${escapeAttr(turnId)}">
  <h3 class="turn-heading">Turn ${escapeHtml(turnId)} <span class="turn-summary">— ${escapeHtml(summary.join(", "))}</span></h3>
  ${requestLine}
  ${replyLine}
  ${changes.map((c, i) => renderChangeCard(c, i)).join("\n")}
</section>`.trim();
}

export function renderAuditTimeline(records: AuditRecord[]): string {
  if (records.length === 0) return "";
  const rows = records
    .slice()
    .reverse() // most recent first
    .slice(0, 50) // keep the panel usable at scale rather than rendering an unbounded list
    .map(
      (r) =>
        `<li><span class="audit-time">${escapeHtml(r.when)}</span> ` +
        `<span class="audit-who">${escapeHtml(r.who)}</span> ` +
        `<span class="audit-what">${escapeHtml(r.what)}</span>` +
        (r.decision ? ` → <strong>${escapeHtml(r.decision)}</strong>${r.decidedBy ? ` by ${escapeHtml(r.decidedBy)}` : ""}` : "") +
        `</li>`
    )
    .join("\n");
  return `<section class="audit-section"><h3>Audit</h3><ul class="audit-list">${rows}</ul></section>`;
}

export function renderEmptyState(connected: boolean): string {
  if (!connected) {
    return `<div class="empty-state">Not connected. Run <strong>SuperDocs Review: Connect Account</strong> from the command palette.</div>`;
  }
  return `<div class="empty-state">Connected. No agent turns observed yet — this updates automatically as SuperDocs sessions produce edits.</div>`;
}

export function renderWorkspaceBody(args: {
  connected: boolean;
  changesByTurn: Map<string, Change[]>;
  turnRecords: Map<string, TurnRecord>;
  auditRecords: AuditRecord[];
}): string {
  if (args.changesByTurn.size === 0) {
    return renderEmptyState(args.connected);
  }
  const turns = [...args.changesByTurn.entries()]
    .sort((a, b) => b[0].localeCompare(a[0])) // most recent turn first
    .map(([turnId, changes]) => renderTurnSection(turnId, changes, args.turnRecords.get(turnId) ?? null))
    .join("\n");
  return `${turns}\n${renderAuditTimeline(args.auditRecords)}`;
}

/**
 * Full HTML document for the webview, including CSP. `nonce` must be a
 * fresh random value per render — it's what makes the inline `<style>`/
 * `<script>` blocks below the *only* script/style the CSP allows to run,
 * which is what makes document content safe to render as real (sanitized)
 * HTML rather than only as escaped text.
 */
export function renderDocument(bodyHtml: string, nonce: string, cspSource: string): string {
  return `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${cspSource} https: data:; style-src 'nonce-${nonce}'; script-src 'nonce-${nonce}';" />
<style nonce="${nonce}">
  :root { color-scheme: light dark; }
  body { font-family: var(--vscode-font-family); font-size: var(--vscode-font-size, 13px); color: var(--vscode-foreground); background: var(--vscode-editor-background); padding: 4px 12px 24px; margin: 0; }
  h3 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--vscode-descriptionForeground); margin: 20px 0 8px; }
  .turn-heading { display: flex; align-items: baseline; gap: 6px; }
  .turn-summary { text-transform: none; letter-spacing: normal; font-size: 12px; }
  .turn-request, .turn-reply { font-size: 12px; margin: 4px 0; }
  .turn-field-label { color: var(--vscode-descriptionForeground); font-weight: 600; }
  .change-card { border: 1px solid var(--vscode-panel-border); border-radius: 4px; padding: 10px 12px; margin-bottom: 10px; }
  .change-card:focus-visible { outline: 2px solid var(--vscode-focusBorder); outline-offset: 2px; }
  .change-card header { display: flex; align-items: center; gap: 8px; font-size: 12px; flex-wrap: wrap; }
  .change-op { text-transform: uppercase; font-weight: 600; color: var(--vscode-descriptionForeground); }
  .change-chunk { font-family: var(--vscode-editor-font-family, monospace); color: var(--vscode-textPreformat-foreground); }
  .badge { margin-left: auto; font-size: 11px; }
  .badge-match { color: var(--vscode-testing-iconPassed, #3fb950); }
  .badge-danger { color: var(--vscode-testing-iconFailed, #f85149); font-weight: 600; }
  .badge-warn { color: var(--vscode-editorWarning-foreground, #cca700); }
  .badge-muted { color: var(--vscode-descriptionForeground); }
  .claim { font-style: italic; font-size: 12px; margin: 6px 0; }
  .conflict-note { font-size: 12px; color: var(--vscode-editorWarning-foreground, #cca700); margin: 6px 0; }
  .before-after { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin: 8px 0; }
  @media (max-width: 480px) { .before-after { grid-template-columns: 1fr; } }
  .before-after h4 { margin: 0 0 4px; font-size: 11px; color: var(--vscode-descriptionForeground); }
  .doc-fragment, .placeholder { border: 1px solid var(--vscode-panel-border); padding: 6px 8px; font-size: 12px; max-height: 160px; overflow: auto; border-radius: 3px; word-break: break-word; }
  .placeholder { display: block; color: var(--vscode-descriptionForeground); }
  .actions { display: flex; align-items: center; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
  .status-label { font-size: 12px; color: var(--vscode-descriptionForeground); margin-right: auto; }
  button { background: var(--vscode-button-background); color: var(--vscode-button-foreground); border: none; padding: 4px 12px; border-radius: 2px; cursor: pointer; font-size: 12px; }
  button:hover { background: var(--vscode-button-hoverBackground); }
  button.secondary { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); }
  button:focus-visible { outline: 2px solid var(--vscode-focusBorder); outline-offset: 2px; }
  .empty-state { color: var(--vscode-descriptionForeground); padding: 32px 12px; text-align: center; }
  .audit-list { list-style: none; padding: 0; font-size: 12px; }
  .audit-list li { padding: 4px 0; border-bottom: 1px solid var(--vscode-panel-border); }
  .audit-time { color: var(--vscode-descriptionForeground); margin-right: 6px; }
</style>
</head>
<body>
${bodyHtml}
<script nonce="${nonce}">
  const vscode = acquireVsCodeApi();
  document.addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    const action = button.getAttribute('data-action');
    const changeId = button.getAttribute('data-change-id');
    if (!action || !changeId) return;
    vscode.postMessage({ type: 'action', action, changeId });
  });
</script>
</body>
</html>`;
}
