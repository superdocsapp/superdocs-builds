// @ts-check
/**
 * Pure render functions: data in, HTML string out. No DOM access, no
 * fetch, no globals — which is exactly what makes these importable from
 * both the browser (app.js) and a Node test file (test/accessibility.test.js)
 * to run real axe-core checks without needing an actual browser.
 */

export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

const STATUS_LABEL = { PASS: 'Pass', FAIL: 'Fail', UNVERIFIED: 'Unverified', NOT_APPLICABLE: 'Not applicable' };

/** The signature element: a stamp that only looks "impressed" once something is actually verified. */
export function renderStamp(status) {
  const cls = { PASS: 'stamp--pass', FAIL: 'stamp--fail', UNVERIFIED: 'stamp--unverified', NOT_APPLICABLE: 'stamp--na' }[status] || 'stamp--na';
  const glyph = { PASS: '✓', FAIL: '✕', UNVERIFIED: '?', NOT_APPLICABLE: '—' }[status] || '—';
  return `<span class="stamp ${cls}" role="img" aria-label="${STATUS_LABEL[status] || status}"><span aria-hidden="true">${glyph}</span></span>`;
}

export function renderTaskList(tasks) {
  const items = tasks
    .map((t) => {
      const implemented = t.status === 'implemented';
      return `<li class="task-item ${implemented ? 'task-item--live' : 'task-item--dark'}">
        <button type="button" class="task-button" data-task-id="${escapeHtml(t.task_id)}" ${implemented ? '' : 'aria-disabled="true"'}>
          <span class="task-name">${escapeHtml(t.name)}</span>
          <span class="task-status" aria-label="status: ${implemented ? 'implemented' : 'not implemented'}">${implemented ? 'LIVE' : '—'}</span>
        </button>
      </li>`;
    })
    .join('\n');
  return `<ul class="task-list">${items}</ul>`;
}

export function renderVerificationCenter(rows) {
  if (!rows || rows.length === 0) {
    return `<p class="empty-state">No verification has run yet. Apply a decision set to populate this panel.</p>`;
  }
  const items = rows
    .map(
      (r) => `<li class="verify-row">
        ${renderStamp(r.status)}
        <div class="verify-row-body">
          <span class="verify-row-area">${escapeHtml(r.area)}</span>
          <span class="verify-row-detail">${escapeHtml(r.detail)}</span>
        </div>
      </li>`,
    )
    .join('\n');
  return `<ul class="verify-list">${items}</ul>`;
}

const MATERIALITY_CLASS = { material: 'chip--material', minor: 'chip--minor', cosmetic: 'chip--cosmetic', 'review-required': 'chip--review' };

export function renderChangeCard(entry, { editingChangeId = null } = {}) {
  const { changeId, decision, change } = entry;
  const isEditing = changeId === editingChangeId;
  const findingsHtml = change.findings
    .map((f) => `<span class="chip ${MATERIALITY_CLASS[f.materiality] || ''}">${escapeHtml(f.category)} · ${escapeHtml(f.materiality)}</span>`)
    .join(' ');
  const whyHtml = change.findings.map((f) => `<p class="change-why">${escapeHtml(f.why)}</p>`).join('');
  const excerpt = change.baseText || change.targetText || (change.items ? change.items.map((i) => i.text).join(' ') : '');

  const editFormHtml = isEditing
    ? `<div class="edit-form">
        <label class="edit-form-label" for="edit-textarea-${escapeHtml(changeId)}">Replacement text</label>
        <textarea id="edit-textarea-${escapeHtml(changeId)}" class="edit-textarea" rows="3">${escapeHtml(change.targetText || change.baseText || '')}</textarea>
        <div class="change-actions">
          <button type="button" class="decide-btn decide-btn--active" data-edit-save="${escapeHtml(changeId)}">Save edit</button>
          <button type="button" class="decide-btn" data-edit-cancel="${escapeHtml(changeId)}">Cancel</button>
        </div>
      </div>`
    : '';

  return `<li class="change-card" data-change-id="${escapeHtml(changeId)}">
    <div class="change-card-head">
      <span class="change-id">${escapeHtml(changeId)}</span>
      ${findingsHtml}
    </div>
    <p class="change-excerpt">${escapeHtml(excerpt.slice(0, 160))}${excerpt.length > 160 ? '…' : ''}</p>
    ${whyHtml}
    ${
      isEditing
        ? editFormHtml
        : `<div class="change-actions" role="group" aria-label="Decision for ${escapeHtml(changeId)}">
      <button type="button" class="decide-btn ${decision === 'approved' ? 'decide-btn--active' : ''}" data-change-id="${escapeHtml(changeId)}" data-decision="approved">Approve</button>
      <button type="button" class="decide-btn ${decision === 'rejected' ? 'decide-btn--active' : ''}" data-change-id="${escapeHtml(changeId)}" data-decision="rejected">Reject</button>
      <button type="button" class="decide-btn ${decision === 'edited' ? 'decide-btn--active' : ''}" data-edit-open="${escapeHtml(changeId)}">Edit…</button>
    </div>`
    }
    <p class="change-decision-state">Status: <strong>${escapeHtml(decision)}</strong></p>
  </li>`;
}

export function renderChangeList(approvalSet, opts = {}) {
  if (!approvalSet || approvalSet.length === 0) {
    return `<p class="empty-state">Compare two documents to see proposed changes here.</p>`;
  }
  return `<ul class="change-list">${approvalSet.map((entry) => renderChangeCard(entry, opts)).join('\n')}</ul>`;
}

export function renderSummaryBar(summary) {
  if (!summary) return '';
  return `<div class="summary-bar" role="status">
    <span>${summary.total} changes</span>
    <span class="dot" aria-hidden="true">·</span>
    <span>${summary.approved} approved</span>
    <span class="dot" aria-hidden="true">·</span>
    <span>${summary.rejected} rejected</span>
    <span class="dot" aria-hidden="true">·</span>
    <span>${summary.edited} edited</span>
    <span class="dot" aria-hidden="true">·</span>
    <span>${summary.pending} pending</span>
  </div>`;
}

export function renderTimelineEntry({ at, msg, level }) {
  const cls = level === 'error' ? 'timeline-entry--error' : '';
  const time = new Date(at).toLocaleTimeString();
  return `<li class="timeline-entry ${cls}"><span class="timeline-time">${escapeHtml(time)}</span><span class="timeline-msg">${escapeHtml(msg)}</span></li>`;
}

export function renderTimeline(entries) {
  if (!entries || entries.length === 0) return `<p class="empty-state">No activity yet.</p>`;
  return `<ol class="timeline-list">${entries.map(renderTimelineEntry).join('\n')}</ol>`;
}

export function renderVaultGraph(graph, currentId) {
  if (!graph || graph.length === 0) return `<p class="empty-state">No versions committed yet.</p>`;
  const items = graph
    .map((v) => {
      const isCurrent = v.versionId === currentId;
      return `<li class="vault-entry ${isCurrent ? 'vault-entry--current' : ''}">
        <span class="vault-kind">${escapeHtml(v.kind)}</span>
        <span class="vault-fingerprint">${escapeHtml(v.fingerprint.slice(0, 10))}</span>
        ${isCurrent ? '<span class="vault-current-badge">current</span>' : `<button type="button" class="vault-revert-btn" data-revert-to="${escapeHtml(v.versionId)}" aria-label="Revert to version ${escapeHtml(v.fingerprint.slice(0, 10))}">Revert to this</button>`}
      </li>`;
    })
    .join('\n');
  return `<ul class="vault-list">${items}</ul>`;
}

/** Structured error, matching the directive's Error UX spec — never "something went wrong." */
export function renderError({ whatHappened, why, nextActions }) {
  const actions = (nextActions || ['Retry']).map((a) => `<button type="button" class="error-action-btn">${escapeHtml(a)}</button>`).join('');
  return `<div class="error-panel" role="alert">
    <p class="error-what">${escapeHtml(whatHappened)}</p>
    <p class="error-why">${escapeHtml(why)}</p>
    <div class="error-actions">${actions}</div>
  </div>`;
}
